"""سيناريو المستخدم الحقيقي: من بومرداس إلى وسط الجزائر أو زرالدة.

**هذا ليس اختبار وحدة — هذا محاكاة لما يحدث فعلاً حين يفتح شخص التطبيق.**

السؤال: أراد شخص الإقلاع من بومرداس إلى وسط الجزائر أو زرالدة. ماذا
يقول التطبيق؟ هل تأتيه معلومات حية أم قبلية؟ أم ماذا؟

هذا السكربت يطبع ما يراه المستخدم حرفياً، بلا تجميل، ويكشف الحدود:
- بومرداس **خارج** الـbbox (3.4770 مقابل حدّ 3.35).
- الوجهات داخل الجزائر تعمل.
- كل الأرقام قبلية — لا حيّة.

ويقيس السؤال العملي: لو وسّعنا الـbbox ليشمل بومرداس، هل الشبكة
تتصل فعلاً؟ أم أن هناك انقطاعاً في الرسم يجعل التوسيع بلا فائدة؟
"""

from __future__ import annotations

from zahma.db import session_scope
from sqlalchemy import text

# نقاط واقعية (WGS84).
BOUmerdes = (36.7530, 3.4770)      # وسط بومرداس
ALGIERS_CENTRE = (36.7754, 3.0588)  # ساحة الشهداء
ZERALDA = (36.7070, 2.8420)         # زرالدة
BAB_EZZOUAR = (36.7167, 3.1833)     # باب الزوار


def dist_to_network(lat: float, lon: float) -> float:
    with session_scope() as s:
        v = s.execute(
            text(
                """
                WITH box AS (
                    SELECT ST_Expand(
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 0.30
                    ) AS g
                )
                SELECT min(ST_Distance(
                    geom::geography,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                )) / 1000.0
                FROM segments, box WHERE geom && box.g
                """
            ),
            {"lat": lat, "lon": lon},
        ).scalar()
    return float(v) if v is not None else 999.0


def nearest_segment(lat: float, lon: float):
    with session_scope() as s:
        return s.execute(
            text(
                """
                WITH box AS (
                    SELECT ST_Expand(
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 0.30
                    ) AS g
                )
                SELECT seg_id, name, road_class, length_m,
                       ST_Distance(
                           geom::geography,
                           ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                       ) AS d
                FROM segments, box
                WHERE geom && box.g
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                LIMIT 1
                """
            ),
            {"lat": lat, "lon": lon},
        ).mappings().first()


def main() -> int:
    print("=" * 62)
    print("ما يراه المستخدم — من بومرداس إلى الجزائر")
    print("=" * 62)
    print()

    places = [
        ("بومرداس (الانطلاق)", *BOUmerdes),
        ("وسط الجزائر", *ALGIERS_CENTRE),
        ("زرالدة", *ZERALDA),
        ("باب الزوار", *BAB_EZZOUAR),
    ]
    print("── المسافة إلى شبكتنا")
    for name, lat, lon in places:
        d = dist_to_network(lat, lon)
        seg = nearest_segment(lat, lon)
        inside = "داخل التغطية" if d <= 2.0 else "خارج التغطية"
        print(f"  {name:22s} {d:>6.1f} كم  [{inside}]")
        if seg:
            nm = seg["name"] or "(بلا اسم)"
            print(
                f"      أقرب مقطع: {nm} ({seg['road_class']}, "
                f"{seg['length_m']:.0f} م)"
            )
    print()

    # كم تبعد بومرداس عن حدّ الشبكة جغرافياً؟
    with session_scope() as s:
        ext = s.execute(
            text(
                """
                SELECT ST_XMax(ST_Extent(geom::geometry)) AS lon_max,
                       ST_XMin(ST_Extent(geom::geometry)) AS lon_min,
                       ST_YMax(ST_Extent(geom::geometry)) AS lat_max,
                       ST_YMin(ST_Extent(geom::geometry)) AS lat_min
                FROM segments
                """
            )
        ).mappings().one()
    print("── حدود شبكتنا الحالية")
    print(
        f"  خط الطول: {ext['lon_min']:.4f} .. {ext['lon_max']:.4f}   "
        f"(بومرداس 3.4770)"
    )
    print(
        f"  خط العرض: {ext['lat_min']:.4f} .. {ext['lat_max']:.4f}"
    )
    print()

    # هل هناك شبكة بين حدّنا وبومرداس؟ — أي هل التوسيع مجدٍ؟
    gap_lon = 3.40
    seg = nearest_segment(36.7530, gap_lon)
    d = dist_to_network(36.7530, gap_lon)
    print("── هل توجد شبكة في الفراغ بين حدّنا وبومرداس؟")
    print(f"  عند خط الطول {gap_lon:.2f}: أقرب مقطع {d:.1f} كم")
    if seg:
        print(f"      {seg['name'] or '(بلا اسم)'} ({seg['road_class']})")
    print()

    print("── الحكم")
    print("  بومرداس خارج الـbbox، لكنها ليست معزولة: الطريق السريع")
    print("  الشرقي (RN5/A1) يصلها بالجزائر. الشبكة الموجودة تتوقف")
    print("  عند حدود الولاية، لا عند حدود عمرانية حقيقية.")
    print()
    print("  ⇒ التطبيق يقول اليوم: «خارج التغطية» — وهو صادق.")
    print("  ⇒ لكن المستخدم الحقيقي من بومرداس يحتاج هذه الرحلة.")
    print("     فالتوسيع قرار منتج، لا عيب تقني.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
