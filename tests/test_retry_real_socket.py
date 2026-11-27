"""إثبات حقيقي لـ retry: مقبس يقطع الاتصال فعلاً، لا محاكاة.

الاختبارات في `test_network_resilience.py` تستخدم `MockTransport` — وهي
تثبت المنطق لكنها لا تلمس الشبكة. هنا نقيم مقبساً على 127.0.0.1 يغلق
الاتصال بلا رد (وهو ما يفعله مزوّد يسقط أو جدار ناري يقطع)، ونتأكد أن
`RetryingClient` يتعافى فعلاً.

**لماذا هذا مهم:** `MockTransport` يستدعي المعالج مباشرة، فلا يمر عبر
`httpx` الحقيقي ولا يُنتج `ConnectError`/`ReadError` حقيقياً. لو كان
الغلاف يلتقط نوع استثناء خاطئاً، لمرّ الاختبار الوهمي ونجح، وفشل
الإنتاج. هذا الاختبار يغلق تلك الفجوة.
"""

from __future__ import annotations

import socket
import threading
import time

from zahma.collect.http import RetryingClient


def _serve_once_then_close(port_holder: dict, hits: dict) -> None:
    """يخدم اتصالاً واحداً: يقطعه بلا رد ثم يخدم نجاحاً."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port_holder["port"] = srv.getsockname()[1]
    srv.settimeout(10)

    while hits["n"] < 2:
        try:
            c, _ = srv.accept()
        except TimeoutError:
            break
        hits["n"] += 1
        if hits["n"] == 1:
            # انقطاع حقيقي: نغلق بلا أي بايت رد.
            c.close()
            continue
        c.recv(4096)
        body = b'{"ok":true}'
        c.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + body
        )
        c.close()
    srv.close()


class TestRealSocketRecovery:
    """التعافي من انقطاع حقيقي، لا من محاكاة."""

    def test_recovers_from_a_real_dropped_connection(self):
        """أول اتصال يُقطع، الثاني ينجح، والمحاولات = 2.

        هذا هو سيناريو «الشبكة قطعت لحظة» بالضبط. قبل الإصلاح كان أول
        فشل يُسقط الزوج كاملاً.
        """
        holder: dict = {}
        hits = {"n": 0}
        t = threading.Thread(
            target=_serve_once_then_close, args=(holder, hits), daemon=True
        )
        t.start()

        # ننتظر حتى يُفتح المقبس فعلاً.
        for _ in range(50):
            if holder.get("port"):
                break
            time.sleep(0.02)

        with RetryingClient(
            timeout=5.0, backoff=(0.1, 0.2, 0.3)
        ) as client:
            r = client.get(f"http://127.0.0.1:{holder['port']}/x")
            attempts = client.last_attempts

        t.join(timeout=5)

        assert r.status_code == 200
        assert r.json() == {"ok": True}
        assert attempts == 2, (
            f"{attempts} محاولة — الانقطاع الحقيقي لم يُعَد كما ينبغي"
        )
        assert hits["n"] == 2

    def test_a_dead_port_raises_after_retries_not_hangs(self):
        """منفذ مغلق تماماً: يرفع بعد المحاولات، لا يعلّق للأبد."""
        import httpx
        import pytest

        # منفذ مُستخدَم سابقاً ومُغلق الآن ⇒ رفض اتصال فوري.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        start = time.monotonic()
        with RetryingClient(timeout=2.0, backoff=(0.05, 0.05, 0.05)) as client:
            with pytest.raises(httpx.TransportError):
                client.get(f"http://127.0.0.1:{port}/x")
            attempts = client.last_attempts
        elapsed = time.monotonic() - start

        assert attempts == 4, f"{attempts} محاولة بدل 4"
        assert elapsed < 15, f"استغرق {elapsed:.1f} ث — retry يعلّق"
