import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _run_sync() -> None:
    import database
    from email_client import EmailSyncError, fetch_invoices_from_mailbox

    try:
        database.init_db()
        result = fetch_invoices_from_mailbox()
        for invoice in result["invoices"]:
            database.upsert_invoice(invoice)
        logger.info(
            "Sincronización automática: %s correos, %s facturas",
            result["scanned"],
            len(result["invoices"]),
        )
    except EmailSyncError as exc:
        logger.warning("Sincronización automática fallida: %s", exc)


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
