"""الاختبار الحاسم: هل يعتمد الرد على وقت *الطلب* أم على `depart_at` فقط؟

**الخطأ في استدلالي السابق:** قارنت `2026-12-02` و`2026-12-09` و
`2027-03-03` فوجدتها متطابقة (1575.8)، فاستنتجت «الجدول ثابت». لكنني
استدعيتها **في نفس الثانية**. إن كان هناك مكوّن حي، فلن يتغير بين
استدعاءين متتاليين.

والدليل المضاد من القاعدة: المقطع 47490 عند 23:00 يعطي 9.92 في
2026-11-29 و33.82 في 2026-12-06 — نفس يوم الأسبوع، نفس الساعة. هذه
القياسات جُمعت في **أوقات حقيقية مختلفة**.

**الاختبار الصحيح:** نثبّت `depart_at` ونغيّر وقت الطلب. إن تغيّر الرد
فهناك مكوّن حي، وادعاء «الفائت يُملأ» خاطئ.
"""

from __future__ import annotations

import time

import httpx

from zahma.config import get_settings

BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"
COORDS = "3.1,36.74;2.84,36.71"  # pair 15


def dur(depart_at: str) -> float:
    s = get_settings()
    r = httpx.get(
        f"{BASE}/{COORDS}",
        params={
            "access_token": s.mapbox_token,
            "overview": "false",
            "depart_at": depart_at,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["routes"][0]["duration"]


def main() -> int:
    fixed = "2026-11-29T23:00"

    print(f"depart_at ثابت = {fixed}")
    print("نكرّر الطلب كل 15 ثانية — نفس المعامل حرفياً")
    print()
    vals = []
    for i in range(6):
        v = dur(fixed)
        vals.append(v)
        print(f"  محاولة {i + 1}: {v:.2f} ث")
        if i < 5:
            time.sleep(15)

    print()
    spread = max(vals) - min(vals)
    print(f"المدى: {spread:.2f} ثانية على {len(vals)} استدعاءات")
    print()
    if spread < 0.01:
        print("⇒ الرد لا يعتمد على وقت الطلب. الجدول ثابت فعلاً.")
        print("   إذن اختلاف القاعدة سببه كودنا لا المصدر.")
    else:
        print("⇒ **الرد يتغير مع وقت الطلب.** هناك مكوّن حي.")
        print("   ادعاء «الفائت يُملأ بلا خسارة» خاطئ ويجب تصحيحه:")
        print("   الملء يعيد حالة اللحظة الحالية، لا حالة الساعة الفائتة.")

    print()
    print("─" * 50)
    print("اختبار مقارن: ساعات مختلفة بنفس اللحظة")
    for hh in ("03:00", "08:00", "17:00"):
        print(f"  {fixed[:10]}T{hh}: {dur(f'{fixed[:10]}T{hh}'):.2f} ث")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
