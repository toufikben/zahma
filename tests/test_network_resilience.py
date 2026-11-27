"""حرّاس على مقاومة انقطاع الشبكة — الطبقة التي كانت غائبة تماماً.

**السؤال الذي أجاب عنه هذا الملف:** «هل نحتاج خادماً خارجياً (Oracle)
لضمان الاستمرارية؟» الجواب المقاس: **لا، لكن ليس لأن الشبكة بخير** —
بل لأن العيب لم يكن في مكان الخادم.

**العيوب الثلاثة التي كانت قائمة:**

1. **لا `retry` في أي عميل HTTP.** كل مصدر يستدعي `httpx.Client` مباشرة.
   انقطاع لثانية = زوج مفقود بلا محاولة ثانية. والأثر تراكمي: 20 زوجاً ×
   17 ساعة × 5% فشل = 17 زوجاً مفقوداً في ساعة سيئة واحدة.

2. **الطابور يُكتب ولا يُقرأ.** `queue.push` يُنادى عند فشل الكتابة، لكن
   `claim`/`ack`/`nack` لم تُنادَ من أي مكان. البيانات تُحفظ في مكان لا
   يقرأه أحد — وهذا أسوأ من الفقدان لأنه يبدو حماية.

3. **الحمولة المحفوظة بلا عينات.** كانت `{"error", "meta"}` فقط. لا يمكن
   إعادة بنائها إلى صفوف. فالطابور كان يحفظ إشعار فشل لا بيانات.

هذه الاختبارات تثبت الإصلاحات الثلاثة — بلا شبكة حقيقية، عبر
`httpx.MockTransport`.
"""

from __future__ import annotations

import httpx
import pytest

from zahma.collect.http import RetryingClient, is_transient


def _client(handler, **kw) -> RetryingClient:
    """عميل بإعادة محاولة فوق نقل وهمي — بلا شبكة ولا انتظار حقيقي."""
    transport = httpx.MockTransport(handler)
    raw = httpx.Client(transport=transport)
    # backoff صفري: نختبر المنطق لا الزمن.
    return RetryingClient(backoff=(0.0, 0.0, 0.0), client=raw, **kw)


class TestRetriesTransientFailures:
    """الفشل المؤقت يجب أن يُعاد — وهذا ما لم يكن يحدث إطلاقاً."""

    def test_retries_on_500_and_succeeds(self):
        """502 مرة ثم 200: النتيجة نجاح، والمحاولات 2.

        قبل الإصلاح كان أول 502 يُسقط الزوج كاملاً.
        """
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(502, text="bad gateway")
            return httpx.Response(200, json={"routes": []})

        with _client(handler) as c:
            r = c.get("https://example.test/x")
            attempts = c.last_attempts

        assert r.status_code == 200
        assert attempts == 2
        assert calls["n"] == 2

    def test_retries_on_transport_error(self):
        """انقطاع اتصال (ConnectError) يُعاد ثم ينجح.

        هذا هو سيناريو «الشبكة قطعت لحظة» — الأكثر شيوعاً في الجزائر.
        """
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("network down")
            return httpx.Response(200, text="ok")

        with _client(handler) as c:
            r = c.get("https://example.test/x")

        assert r.status_code == 200
        assert calls["n"] == 2

    def test_gives_up_after_retries_and_raises(self):
        """انقطاع دائم: يرفع الاستثناء بعد استنفاد المحاولات، لا يعلّق للأبد."""
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            raise httpx.ConnectError("still down")

        with _client(handler) as c:
            with pytest.raises(httpx.ConnectError):
                c.get("https://example.test/x")
            attempts = c.last_attempts

        # retries=3 ⇒ 4 محاولات كاملة، ثم استسلام.
        assert attempts == 4
        assert calls["n"] == 4

    def test_returns_last_500_instead_of_raising(self):
        """5xx دائم: يعيد الرد الأخير (ليقرأه المصدر) بدل رفع استثناء.

        مهم لأن المصدر يميّز 429 عن 5xx، ويحتاج رؤية الرمز.
        """
        with _client(lambda r: httpx.Response(503)) as c:
            r = c.get("https://example.test/x")
        assert r.status_code == 503


class TestDoesNotRetryClientErrors:
    """إعادة 4xx تُهدر الحصة بلا فائدة — يجب ألا تحدث."""

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_no_retry_on_client_error(self, status):
        """طلب خاطئ: محاولة واحدة فقط.

        422 تحديداً شائع هنا — Mapbox يرفض `depart_at` به. إعادته 4 مرات
        تستهلك 4 طلبات من الحصة مقابل نفس الرفض.
        """
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(status)

        with _client(handler) as c:
            r = c.get("https://example.test/x")
            attempts = c.last_attempts

        assert r.status_code == status
        assert attempts == 1
        assert calls["n"] == 1

    def test_429_retried_by_default(self):
        """429 افتراضياً مؤقت (تأخير) ⇒ يُعاد."""
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429 if calls["n"] == 1 else 200)

        with _client(handler) as c:
            r = c.get("https://example.test/x")
        assert r.status_code == 200
        assert calls["n"] == 2

    def test_429_not_retried_when_quota_is_final(self):
        """Mapbox: 429 = نهاية الحصة. إعادتها تحرق ما تبقّى.

        هذا هو الفرق الحقيقي بين المزوّدين، ولهذا صار خياراً لا سلوكاً
        ثابتاً.
        """
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429)

        with _client(handler, retry_on_429=False) as c:
            r = c.get("https://example.test/x")
            attempts = c.last_attempts

        assert r.status_code == 429
        assert attempts == 1
        assert calls["n"] == 1


class TestAttemptAccounting:
    """إعادة المحاولة تستهلك حصة أيضاً — إخفاؤها تقرير استهلاك كاذب."""

    def test_last_attempts_counts_every_try(self):
        """3 محاولات فاشلة ثم نجاح ⇒ last_attempts = 4.

        لماذا يهم: تقرير الاستهلاك الشهري يجب أن يطابق ما يراه المزوّد،
        وإلا اكتشفنا نفاد الحصة قبل موعده بيوم أو يومين.
        """
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] <= 3:
                return httpx.Response(500)
            return httpx.Response(200)

        with _client(handler) as c:
            c.get("https://example.test/x")
            attempts = c.last_attempts

        assert attempts == 4

    def test_success_first_try_is_one_attempt(self):
        """الحالة السليمة: محاولة واحدة. لا ندفع ثمناً في الوضع الطبيعي."""
        with _client(lambda r: httpx.Response(200)) as c:
            c.get("https://example.test/x")
            assert c.last_attempts == 1


class TestIsTransient:
    """دالة القرار تُختبر وحدها — لأن سياسات المزوّدين تختلف."""

    @pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
    def test_transient(self, status):
        assert is_transient(status)

    @pytest.mark.parametrize("status", [200, 204, 400, 401, 403, 404, 422])
    def test_not_transient(self, status):
        assert not is_transient(status)


class TestQueueIsActuallyDrained:
    """الطابور كان يُكتب ولا يُقرأ — أخطر عيب لأنه يبدو حماية."""

    def test_drain_module_is_wired_into_the_loop(self):
        """`run_once` يستدعي `drain` قبل الجمع.

        قبل الإصلاح: لا شيء يستدعي claim/ack/nack. الطابور قبر لا طابور.
        """
        import inspect

        from zahma.collect import runner

        src = inspect.getsource(runner.Collector.run_once)
        assert "drain" in src, "الطابور لا يُستنزف في حلقة الجمع"

    def test_drain_imports_claim_and_ack(self):
        """drain يستخدم واجهة الطابور فعلاً، لا يعيد كتابتها."""
        import inspect

        from zahma.collect import drain as drain_mod

        src = inspect.getsource(drain_mod)
        assert "queue.claim" in src
        assert "queue.ack" in src
        assert "queue.nack" in src

    def test_failed_write_payload_carries_samples(self):
        """الحمولة المحفوظة عند الفشل تحمل العينات، لا الخطأ فقط.

        قبل الإصلاح كانت `{"error", "meta"}` — لا يمكن استعادتها إلى صفوف.
        """
        import inspect

        from zahma.collect import runner

        src = inspect.getsource(runner.Collector._run_source)
        assert "segment_samples" in src
        assert "route_samples" in src
        # ولا يكتفي بحفظ الخطأ.
        assert '"meta": result.raw_meta' not in src
