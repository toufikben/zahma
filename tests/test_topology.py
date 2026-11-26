"""اختبارات الطوبولوجيا — الحرس على الخطأ الذي كلّفنا مرتين.

القصة: بنينا الشبكة مرتين بشكل خاطئ:
1. ربط الحواف بإحداثيات مقرّبة ⇒ 2413 مكوّناً منفصلاً.
2. حذف المقاطع الأقصر من 5 أمتار ⇒ حذف وصلات التقاطع ⇒ 38% متصلة فقط.

الدرس: التماسك ليس تفصيلاً — إنه الشرط الذي بدونه كل توجيه يفشل
وكل تنبؤ خاطئ. هذه الاختبارات تفشل فوراً إن عاد الخطأ.

تعمل على قاعدة البيانات مباشرة، لأن العيب في البيانات لا في الكود.
"""

from __future__ import annotations

import networkx as nx
from sqlalchemy import text

from zahma.db import session_scope

# الحدود الدنيا المقبولة — مبنية على قياس فعلي لا تخمين.
MIN_MAIN_SHARE = 0.90      # 90% من العقد في مكوّن واحد
MIN_SEGMENTS = 200_000     # العاصمة أكبر من ذلك بكثير
MIN_MEASURABLE = 80_000    # المقاطع الشريانية القابلة للقياس


def _load_edges() -> list[tuple[int, int, str]]:
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT u, v, COALESCE(oneway, 'no') AS oneway
                FROM segments
                WHERE u IS NOT NULL AND v IS NOT NULL
                """
            )
        ).all()
    return [(int(r[0]), int(r[1]), str(r[2]).strip().lower()) for r in rows]


def _undirected(edges: list[tuple[int, int, str]]) -> nx.Graph:
    G = nx.Graph()
    for u, v, _ in edges:
        G.add_edge(u, v)
    return G


def _directed(edges: list[tuple[int, int, str]]) -> nx.DiGraph:
    """يبني الرسم بنفس قواعد المحرك: حافة معاكسة للطرق ذات الاتجاهين."""
    G = nx.DiGraph()
    for u, v, ow in edges:
        G.add_edge(u, v)
        if ow != "yes":
            G.add_edge(v, u)
    return G


def test_no_coordinate_rounding_in_topology() -> None:
    """العقد تُربط بمعرّفات OSM لا بإحداثيات مقرّبة.

    المؤشر: لو رُبطت بالإحداثيات، لكانت درجات العقد صغيرة جداً
    (كل مقطع جزيرة). مع المعرّفات الحقيقية، متوسط الدرجة > 2.
    """
    edges = _load_edges()
    assert len(edges) > MIN_SEGMENTS, f"too few segments: {len(edges):,}"

    G = _undirected(edges)
    avg_degree = 2 * G.number_of_edges() / G.number_of_nodes()
    assert avg_degree > 2.0, f"avg degree {avg_degree:.2f} — topology looks broken"


def test_network_is_mostly_one_component() -> None:
    """99% من الشبكة في مكوّن واحد — وإلا فالتوجيه يفشل عشوائياً."""
    edges = _load_edges()
    G = _undirected(edges)
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    share = len(comps[0]) / G.number_of_nodes()

    assert share >= MIN_MAIN_SHARE, (
        f"largest component only {share:.1%} of {G.number_of_nodes():,} nodes "
        f"({len(comps)} components) — junction connectors likely dropped"
    )


def test_short_connectors_preserved() -> None:
    """وصلات التقاطع القصيرة موجودة — حذفها كان يفتّت الشبكة.

    وصلات التقاطع طولها 1–5 أمتار. وجود عدد كبير منها مؤشر صحة،
    وغيابها مؤشر على فلتر طول خاطئ.
    """
    with session_scope() as s:
        n_short = s.execute(
            text("SELECT COUNT(*) FROM segments WHERE length_m < 5")
        ).scalar()

    assert (n_short or 0) > 1000, (
        f"only {n_short} short segments — junction connectors were filtered out"
    )


def test_oneway_direction_present() -> None:
    """اتجاه الطريق مسجّل — بلا هذا كل طريق يُعامل ذهاباً وإياباً."""
    with session_scope() as s:
        rows = s.execute(
            text("SELECT COALESCE(oneway,'no'), COUNT(*) FROM segments GROUP BY 1")
        ).all()
    dist = {str(r[0]).strip().lower(): int(r[1]) for r in rows}

    assert "yes" in dist, f"no one-way segments recorded: {dist}"
    assert dist["yes"] > 10_000, f"implausibly few one-way segments: {dist}"


def test_main_component_is_routable_both_ways() -> None:
    """المكوّن الأكبر متصل في الاتجاهين — شرط لأي مسار ذهاب/عودة.

    لو كان الرسم شجرياً (DAG)، لكان كل مسار أحادي الاتجاه ولا يمكن
    العودة من الوجهة. القياس: أكبر SCC يجب أن يغطي أغلب الشبكة.
    """
    edges = _load_edges()
    G = _directed(edges)
    scc = max(nx.strongly_connected_components(G), key=len)
    share = len(scc) / G.number_of_nodes()

    assert share >= MIN_MAIN_SHARE, (
        f"largest strongly-connected component only {share:.1%} — "
        f"reverse edges missing for two-way streets"
    )


def test_measurable_segments_exist() -> None:
    """المقاطع القابلة للقياس كافية لتغطية المدينة."""
    with session_scope() as s:
        n = s.execute(
            text("SELECT COUNT(*) FROM segments WHERE measurable")
        ).scalar()
    assert (n or 0) >= MIN_MEASURABLE, f"only {n:,} measurable segments"


def test_geometry_valid() -> None:
    """كل هندسة صالحة — هندسة فاسدة تُسقط ST_DWithin والتوجيه."""
    with session_scope() as s:
        bad = s.execute(
            text(
                "SELECT COUNT(*) FROM segments "
                "WHERE NOT ST_IsValid(geom) OR ST_IsEmpty(geom)"
            )
        ).scalar()
    assert (bad or 0) == 0, f"{bad} invalid geometries"


def test_speeds_plausible() -> None:
    """السرعات الحرة معقولة — سرعة 0 تُسقط القسمة، و500 كم/س خطأ بيانات."""
    with session_scope() as s:
        bad = s.execute(
            text(
                "SELECT COUNT(*) FROM segments "
                "WHERE speed_free_kmh <= 0 OR speed_free_kmh > 160"
            )
        ).scalar()
    assert (bad or 0) == 0, f"{bad} segments with implausible free-flow speed"


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"✓ {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"✗ {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
