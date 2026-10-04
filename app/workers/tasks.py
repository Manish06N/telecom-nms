from celery import Celery

from app.core.config import settings

celery_app = Celery("telecom", broker=settings.redis_url or "redis://localhost:6379/0")
celery_app.conf.task_always_eager = False


def run_schedules_task():
    """Imported by the Celery task below. Kept separate so tests can call the service directly."""
    from app.db.session import SessionLocal
    from app.services.operations_service import run_schedules

    db = SessionLocal()
    try:
        result = run_schedules(db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="telecom.run_schedules")
def run_schedules_task_celery():
    return run_schedules_task()
