"""عميل HTTP مقاوم لانقطاع الشبكة — الطبقة التي كانت غائبة.

**العيب الذي يصلحه:** لا عميل HTTP في المشروع كان يملك `retry`. كل
مصدر يستخدم `httpx.Client(timeout=...)` مباشرة. فإذا انقطع الاتصال
لثانية واحدة، أو أعاد المزوّد 502، أو تأخّر الرد:

- الطلب يفشل فوراً.
- `mapbox.fetch` يلتقط الاستثناء ويضيفه إلى `errors` ويُكمل الزوج التالي.
- الزوج الفاشل **يُفقد بلا محاولة ثانية**.

والأثر تراكمي: 20 زوجاً × 17 ساعة، فإذا فشل 5% من الطلبات في ساعة
سيئة خسرنا ~17 زوجاً لتلك الساعة بلا سبب وجيه. و«انقطاع الشبكة» في
الجزائر ليس نادراً — هو الحالة الطبيعية التي يجب أن يتعامل معها
الكود لا أن يُفاجأ بها.

**القرارات المقاسة:**
- `retries=3` بفواصل 0.5/1.5/4 ثانية: أقل من ثانية إجمالاً في الحالة
  السليمة، ويكفي لتجاوز انقطاع قصير.
- **لا إعادة على 4xx** عدا 429: 400/422 تعني طلباً خاطئاً، وإعادته
  تُهدر الحصة بلا فائدة. 429 (تجاوز الحد) تُعاد لأنها مؤقتة.
- **إعادة على 5xx** لأنها أعطال مؤقتة عند المزوّد.

**ما لا يصلحه هذا:** انقطاع طويل (دقائق). لذلك يبقى الطابور ضرورياً —
هو يحمي البيانات **بعد** أن تُجلب. الطبقتان تعملان معاً: retry للفشل
القصير، والطابور للفشل الطويل في الكتابة.
"""

from __future__ import annotations

import time

import httpx


class RetryingClient:
    """غلاف حول httpx.Client يعيد المحاولة عند الفشل المؤقت."""

    def __init__(
        self,
        timeout: float = 25.0,
        retries: int = 3,
        backoff: tuple[float, ...] = (0.5, 1.5, 4.0),
        client: httpx.Client | None = None,
        retry_on_429: bool = True,
    ):
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.retry_on_429 = retry_on_429
        self._client = client or httpx.Client(timeout=timeout)
        self._owns = client is None
        # عدد المحاولات الفعلية لآخر طلب. مهم للمحاسبة: إعادة المحاولة
        # تستهلك حصة المزوّد أيضاً، فإخفاؤها يعني تقرير استهلاك كاذب.
        self.last_attempts = 0

    def __enter__(self) -> "RetryingClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._owns:
            self._client.close()

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        """GET مع إعادة محاولة. يعيد آخر رد مهما كان حالته.

        الاستثناءات الشبكية (`httpx.TransportError`) تُعاد دائماً — لا
        رد لها أصلاً. أما ردود HTTP فتُعاد فقط إن كانت 5xx أو 429.
        """
        last_exc: Exception | None = None
        last_resp: httpx.Response | None = None
        self.last_attempts = 0

        for attempt in range(self.retries + 1):
            self.last_attempts = attempt + 1
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError as e:
                # انقطاع، DNS، مهلة — كلها مؤقتة بطبيعتها.
                last_exc = e
                if attempt < self.retries:
                    time.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
                    continue
                raise

            # 5xx: عطل عند المزوّد. 429: تجاوز حد مؤقت — إلا عند مزوّد يعدّه
            # نهاية الحصة (Mapbox)، فإعادته تُهدر ما تبقّى منها.
            transient = resp.status_code >= 500 or (
                resp.status_code == 429 and self.retry_on_429
            )
            if transient:
                last_resp = resp
                if attempt < self.retries:
                    time.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
                    continue
                return resp

            # 4xx أخرى (400/401/403/422): طلب خاطئ. إعادته تُهدر الحصة.
            return resp

        if last_resp is not None:
            return last_resp
        raise last_exc or RuntimeError("retrying client: no response")


def is_transient(status: int) -> bool:
    """هل هذا الرد يستحق إعادة المحاولة؟

    دالة منفصلة لأن المنطق يُختبر وحده، ولأن كل مصدر قد يحتاج تعديل
    سياسة مختلفة لاحقاً (مثلاً Mapbox يعدّ 429 نهاية الحصة لا تأخيراً).
    """
    return status >= 500 or status == 429
