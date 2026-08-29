import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _run_sync() -> None:
    from sync_service import get_sync_status, start_sync

    status = get_sync_status()
    if status.get("running"):
        logger.info("Sincronización ya en curso, omitiendo")
        return
    start_sync()
    logger.info("Sincronización automática iniciada")


def start_scheduler() -> None:
    global _scheduler
    hours = int(os.getenv("AUTO_SYNC_HOURS", "4"))
    if hours <= 0 or _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_run_sync, "interval", hours=hours, id="email_sync")
    _scheduler.add_job(_run_sync, "date", id="startup_sync")  # una vez al arrancar
    _scheduler.start()
    logger.info("Programador activo: sincroniza cada %s horas", hours)
