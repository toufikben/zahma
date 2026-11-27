"""محرّك قاعدة البيانات والجلسات."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from zahma.config import get_settings

_engine = None
_Session = None


def get_engine():
    global _engine
    if _engine is None:
        s = get_settings()
        # connect_timeout: بلا هذا، أي اتصال بقاعدة متوقفة ينتظر مهلة TCP
        # (~21 ثانية على ويندوز، ~2 ثانية على لينكس). في اختبارات بلا
        # قاعدة، يتكرر ذلك عشرات المرات فتصل الحزمة إلى 4 دقائق.
        # وفي الإنتاج: خدمة لا تستجيب يجب أن تفشل في ثانيتين لا في 21.
        _engine = create_engine(
            s.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            connect_args={"connect_timeout": 3},
            future=True,
        )
    return _engine


def get_sessionmaker():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _Session


@contextmanager
def session_scope() -> Iterator[Session]:
    """جلسة معاملة آمنة: commit عند النجاح، rollback عند الفشل."""
    s = get_sessionmaker()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def ping() -> dict:
    """فحص الاتصال وإصدار Postgres وتوفر PostGIS."""
    with get_engine().connect() as c:
        ver = c.execute(text("select version()")).scalar_one()
        try:
            postgis = c.execute(text("select postgis_version()")).scalar_one()
        except Exception:
            postgis = None
        tz = c.execute(text("show timezone")).scalar_one()
    return {"version": ver.split(" on ")[0], "postgis": postgis, "timezone": tz}
