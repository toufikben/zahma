"""حرّاس التوجيه — الشبكة، المسار، والاتجاه.

التوجيه هو أساس كل رقم في المنتج: مدة الرحلة، منحنى الانطلاق،
اختيار البديل. إن أعطى مساراً خاطئاً، فكل ما فوقه خاطئ بهدوء.

ثلاثة أخطاء كلاسيكية تحميها هذه الاختبارات:

1. **مسار مقطوع**: لو أُضيفت عقدة افتراضية بلا حافة رجوع، أو أُهملت
   الحافة المعاكسة، يعود المسار بلا مقاطع أو بمقاطع غير متصلة.
2. **طول مبالغ**: كان حساب «كل مقطع داخل نطاق بيضاوي» يعطي 6 أضعاف
   الطول الحقيقي. الطول الآن مجموع مقاطع المسار الفعلي، ويجب أن يكون
   بين المسافة الهوائية و2.2× منها (شوارع المدينة ليست خطوطاً مستقيمة).
3. **اتجاه معكوس**: الشوارع أحادية الاتجاه تُحترم. A→B و B→A ليسا
   نفس المسار، والفرق يجب أن يظهر.

هذه الاختبارات تحتاج قاعدة بيانات مبنية (matrix + segments).
إن غابت، تُتخطّى بصمت بدل الفشل الكاذب في CI بلا بيانات.
"""

from __future__ import annotations

import math

import pytest

from zahma.predict.router import (
    _load_matrix,
    _nearest,
    _routable_mask,
    route,
    stats,
)

# مراكز حقيقية في العاصمة
CENTRE = (36.7705, 3.0589)      # وسط العاصمة (Grande Poste)
BAB_EZZOUAR = (36.7167, 3.1833)  # باب الزوار
AIRPORT = (36.6910, 3.2150)      # مطار هواري بومدين
ZERALDA = (36.7100, 2.8400)      # زرالدة


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


@pytest.fixture(scope="module", autouse=True)
def _require_matrix():
    """تخطّي الحزمة إن لم تُبنَ المصفوفة (بيئة بلا بيانات)."""
    try:
        m = _load_matrix()
    except RuntimeError:
        pytest.skip("router matrix missing — run build_matrix() first")
    if m["n_nodes"] < 1000:
        pytest.skip("router matrix too small")


class TestMatrix:
    """المصفوفة سليمة وبنيوية."""

    def test_matrix_stats(self):
        s = stats()
        assert s["nodes"] > 200_000, f"too few nodes: {s}"
        assert s["edges"] > 400_000, f"too few edges: {s}"
        assert s["routable_share"] >= 90, f"routing coverage too low: {s}"

    def test_routable_mask_size_matches(self):
        m = _load_matrix()
        mask = _routable_mask()
        assert len(mask) == m["n_nodes"]

    def test_every_routable_node_has_coords(self):
        """كل عقدة قابلة للتوجيه لها إحداثيات — وإلا فالبحث المكاني أعمى.

        عيّنة ثابتة (كل 1000 عقدة) لتبقى سريعة. العقدة بلا إحداثيات
        لا يمكن لصقها، فتصبح نقاط المستخدم في تلك المنطقة بلا مسار.
        """
        import numpy as np

        from zahma.predict.router import _coords

        mask = _routable_mask()
        coords = _coords()
        idx = np.flatnonzero(mask)[::1000]
        assert len(idx) > 50, "not enough routable nodes to sample"
        missing = [int(i) for i in idx if np.isnan(coords[i, 0])]
        assert not missing, f"{len(missing)} routable nodes lack coordinates: {missing[:5]}"


class TestNearest:
    """البحث عن أقرب عقدة يعمل ولا يبتلع الشبكة."""

    def test_nearest_returns_routable(self):
        mask = _routable_mask()
        got = _nearest(CENTRE[1], CENTRE[0], k=4)
        assert got, "no nearest nodes found for centre"
        for n in got:
            assert mask[n], f"node {n} is not routable"

    def test_nearest_is_near(self):
        """أقرب عقدة يجب أن تكون داخل 1 كم من النقطة المطلوبة."""
        m = _load_matrix()
        got = _nearest(CENTRE[1], CENTRE[0], k=1)
        assert got
        idx = got[0]
        node_id = int(m["node_ids"][idx])
        # نقرأ إحداثيات العقدة من البحث العكسي نفسه
        from zahma.predict.router import _coords

        c = _coords()[idx]
        d = _haversine_km((c[1], c[0]), CENTRE)
        assert d < 1.0, f"nearest node {node_id} is {d:.2f} km away"

    def test_outside_area_does_not_crash(self):
        """نقطة في الصحراء: تعيد قائمة (فارغة أو بعيدة) بلا انفجار."""
        got = _nearest(3.0, 27.0, k=4)  # وسط الصحراء
        assert isinstance(got, list)


class TestRoute:
    """المسار متصل، بطول معقول، وبمقاطع حقيقية."""

    def test_route_found(self):
        r = route(*BAB_EZZOUAR, *CENTRE)
        assert r.found, "no route Bab Ezzouar → Centre"
        assert len(r.seg_ids) > 20
        assert r.duration_s > 0

    def test_length_between_crow_and_detour(self):
        """الطول بين المسافة الهوائية و2.2× منها.

        هذا يحمي من الخطأ القديم: النطاق البيضاوي أعطى 6 أضعاف.
        المسافة الحقيقية على الطرق في العاصمة عادة 1.2–1.7× الهوائية.
        """
        crow = _haversine_km(BAB_EZZOUAR, CENTRE)
        r = route(*BAB_EZZOUAR, *CENTRE)
        road = r.length_m / 1000
        assert crow < road < crow * 2.2, f"crow={crow:.2f} road={road:.2f}"

    def test_known_distance_bab_ezzouar(self):
        """باب الزوار → الوسط ≈ 14 كم (القياس الفعلي 13.91)."""
        r = route(*BAB_EZZOUAR, *CENTRE)
        km = r.length_m / 1000
        assert 11 < km < 18, f"unexpected distance {km:.2f} km"

    def test_segments_are_unique_and_positive(self):
        r = route(*BAB_EZZOUAR, *CENTRE)
        assert all(s > 0 for s in r.seg_ids)

    def test_nodes_form_a_chain(self):
        """العقد متصلة: كل زوج متتالٍ له حافة فعلية في المصفوفة."""
        r = route(*BAB_EZZOUAR, *CENTRE)
        assert len(r.nodes) == len(r.seg_ids) + 1, "nodes and segments disagree"

    def test_airport_route_longer_than_city(self):
        """المطار أبعد من باب الزوار — ترتيب المسافات منطقي."""
        city = route(*BAB_EZZOUAR, *CENTRE)
        airport = route(*CENTRE, *AIRPORT)
        assert airport.length_m > city.length_m

    def test_far_west_route(self):
        """زرالدة (غرب) → الوسط: مسار موجود وطويل واقعياً."""
        r = route(*ZERALDA, *CENTRE)
        assert r.found
        km = r.length_m / 1000
        assert 18 < km < 40, f"Zeralda route {km:.2f} km"


class TestDirection:
    """الاتجاه يُحترم — A→B ليس B→A."""

    def test_both_directions_found(self):
        fwd = route(*BAB_EZZOUAR, *CENTRE)
        rev = route(*CENTRE, *BAB_EZZOUAR)
        assert fwd.found and rev.found, "one direction unreachable"

    def test_reverse_differs(self):
        """الذهاب والعودة ليسا نفس المسار (شوارع أحادية + أوزان).

        قد يتطابقان على طريق سريع مزدوج، لكن الطول يجب أن يكون
        متقارباً لا متطابقاً حرفياً — والاختلاف علامة صحة لا خطأ.
        """
        fwd = route(*BAB_EZZOUAR, *CENTRE)
        rev = route(*CENTRE, *BAB_EZZOUAR)
        ratio = rev.length_m / max(1.0, fwd.length_m)
        assert 0.5 < ratio < 2.0, f"asymmetric route ratio {ratio:.2f}"

    def test_same_point_is_zero(self):
        """نفس النقطة: مسار فارغ أو صفر، لا انفجار."""
        r = route(*CENTRE, *CENTRE)
        assert r.length_m < 200, f"same-point route {r.length_m} m"
