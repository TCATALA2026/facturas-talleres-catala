import hashlib
import threading
from datetime import datetime, timezone
from typing import Any, Callable

import config
import database
from email_client import EmailSyncError, sync_mailboxes


_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "scanned": 0,
    "pdfs_checked": 0,
    "invoices_found": 0,
    "new_count": 0,
    "current_account": "",
    "error": None,
    "started_at": None,
    "finished_at": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_sync_status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _update(**kwargs: Any) -> None:
    with _lock:
        _state.update(kwargs)


def save_invoice_pdf(email_uid: str, pdf_bytes: bytes) -> str:
    digest = hashlib.sha256(email_uid.encode()).hexdigest()[:20]
    rel_path = f"pdfs/{digest}.pdf"
    full_path = config.DATA_DIR / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(pdf_bytes)
    return rel_path


def _handle_invoice(invoice: dict[str, Any]) -> bool:
    pdf_bytes = invoice.pop("pdf_bytes", None)
    if pdf_bytes:
        invoice["pdf_filename"] = save_invoice_pdf(invoice["email_uid"], pdf_bytes)
    is_new = database.upsert_invoice(invoice)
    with _lock:
        _state["invoices_found"] += 1
        if is_new:
            _state["new_count"] += 1
    return is_new


def _run_sync() -> None:
    try:
        def on_progress(data: dict[str, Any]) -> None:
            _update(
                scanned=data.get("scanned", 0),
                pdfs_checked=data.get("pdfs_checked", 0),
                current_account=data.get("account", ""),
            )

        sync_mailboxes(on_progress=on_progress, on_invoice=_handle_invoice)
        _update(error=None, finished_at=_now_iso())
    except EmailSyncError as exc:
        _update(error=str(exc), finished_at=_now_iso())
    except Exception as exc:
        _update(error=f"Error inesperado: {exc}", finished_at=_now_iso())
    finally:
        _update(running=False, current_account="")


def start_sync(force: bool = False) -> dict[str, Any]:
    if not config.EMAIL_SYNC_ENABLED:
        return {
            "ok": False,
            "started": False,
            "error": "Sincronización de correo desactivada",
        }
    if not config.EMAIL_ACCOUNTS:
        return {
            "ok": False,
            "started": False,
            "error": "Correo no configurado",
        }

    with _lock:
        if _state["running"] and not force:
            return {"ok": True, "started": False, "message": "Sincronización en curso"}
        _state.update(
            {
                "running": True,
                "scanned": 0,
                "pdfs_checked": 0,
                "invoices_found": 0,
                "new_count": 0,
                "current_account": "",
                "error": None,
                "started_at": _now_iso(),
                "finished_at": None,
            }
        )

    thread = threading.Thread(target=_run_sync, daemon=True)
    thread.start()
    return {"ok": True, "started": True}
