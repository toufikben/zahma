"""هل المفتاح يعمل أصلاً؟ نتحقق من بلد معروف التغطية.

إن نجح في أمستردام وفشل في الجزائر، فالمشكلة تغطية لا مفتاح.
إن فشل في الاثنين، فالمفتاح أو المنتج غير مفعّل.
"""

from __future__ import annotations

import httpx

from zahma.config import get_settings

URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

TESTS = [
    ("Amsterdam", 52.3676, 4.9041),
    ("Paris", 48.8566, 2.3522),
    ("Madrid", 40.4168, -3.7038),
    ("Algiers centre", 36.7538, 3.0588),
    ("Algiers Rocade", 36.71876, 3.31856),
    ("Oran", 35.6971, -0.6308),
]


def main() -> int:
    s = get_settings()
    key = getattr(s, "tomtom_key", "")
    print(f"key len={len(key)}\n")

    for name, lat, lon in TESTS:
        try:
            r = httpx.get(
                URL,
                params={"key": key, "point": f"{lat},{lon}", "unit": "KMPH"},
                timeout=20,
            )
        except httpx.HTTPError as e:
            print(f"{name:18} NET ERROR {e}")
            continue

        if r.status_code >= 400:
            print(f"{name:18} HTTP {r.status_code}  {r.text[:100]}")
            continue

        d = r.json().get("flowSegmentData") or {}
        print(
            f"{name:18} OK  cur={d.get('currentSpeed')} "
            f"free={d.get('freeFlowSpeed')} conf={d.get('confidence')} "
            f"frc={d.get('frc')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
