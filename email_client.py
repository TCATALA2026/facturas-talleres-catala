import email
import imaplib
from collections.abc import Callable
from email.message import Message
from typing import Any

from config import EMAIL_ACCOUNTS, IMAP_PORT, IMAP_SERVER, RECIPIENT_NAME
from invoice_parser import (
    decode_mime_header,
    extract_pdf_attachments,
    extract_text_from_pdf,
    format_received_date,
    is_invoice_for_recipient,
    is_purchase_invoice,
    parse_invoice_email,
)


class EmailSyncError(Exception):
    pass


def fetch_invoices_from_mailbox() -> dict:
    """Compatibilidad: sincronización completa en bloque."""
    invoices: list[dict] = []
    totals = {"scanned": 0, "pdfs_checked": 0, "accounts": []}

    def on_invoice(inv: dict[str, Any]) -> bool:
        invoices.append(inv.copy())
        return True

    def on_progress(data: dict[str, Any]) -> None:
        totals["scanned"] = data.get("scanned", 0)
        totals["pdfs_checked"] = data.get("pdfs_checked", 0)

    sync_mailboxes(on_progress=on_progress, on_invoice=on_invoice)
    totals["accounts"] = [a["address"] for a in EMAIL_ACCOUNTS]
    return {
        "invoices": invoices,
        "scanned": totals["scanned"],
        "pdfs_checked": totals["pdfs_checked"],
        "accounts": totals["accounts"],
    }


def sync_mailboxes(
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    on_invoice: Callable[[dict[str, Any]], bool] | None = None,
) -> None:
    if not EMAIL_ACCOUNTS:
        raise EmailSyncError(
            "Configura EMAIL_ACCOUNTS en el archivo .env "
            "(ej: Gerencia@tallerescatala.com,taller@tallerescatala.com)"
        )
    if not RECIPIENT_NAME:
        raise EmailSyncError(
            "Configura RECIPIENT_NAME en .env con tu nombre o razón social "
            "(como aparece en las facturas)"
        )

    total_scanned = 0
    total_pdfs = 0

    for account in EMAIL_ACCOUNTS:
        address = account["address"]
        password = account["password"]
        if not password:
            raise EmailSyncError(
                f"Falta contraseña para {address}. "
                "Añade EMAIL_PASSWORD en .env o inclúyela en EMAIL_ACCOUNTS."
            )

        result = _fetch_account(
            address,
            password,
            on_invoice=on_invoice,
            on_progress=lambda local: on_progress and on_progress(
                {
                    "account": address,
                    "scanned": total_scanned + local["scanned"],
                    "pdfs_checked": total_pdfs + local["pdfs_checked"],
                }
            ),
        )
        total_scanned += result["scanned"]
        total_pdfs += result["pdfs_checked"]


def _fetch_account(
    address: str,
    password: str,
    on_invoice: Callable[[dict[str, Any]], bool] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    scanned = 0
    pdfs_checked = 0

    try:
        mail.login(address, password)
        mail.select("INBOX", readonly=True)

        status, data = mail.uid("search", None, "ALL")
        if status != "OK":
            raise EmailSyncError(f"No se pudo acceder al buzón de {address}")

        uids = data[0].split()

        for uid in uids:
            uid_str = uid.decode()
            status, msg_data = mail.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue

            raw_part = msg_data[0]
            if not isinstance(raw_part, tuple) or len(raw_part) < 2:
                continue

            raw_email = raw_part[1]
            if not isinstance(raw_email, bytes):
                continue

            scanned += 1
            msg = email.message_from_bytes(raw_email)
            pdfs_checked += len(extract_pdf_attachments(msg))

            if on_progress and scanned % 5 == 0:
                on_progress({"scanned": scanned, "pdfs_checked": pdfs_checked})

            matching = _matching_invoice_pdfs(msg)
            if not matching:
                continue

            parsed = _parse_message(address, uid_str, msg, matching)
            if parsed and on_invoice:
                on_invoice(parsed)

        return {"scanned": scanned, "pdfs_checked": pdfs_checked}
    except imaplib.IMAP4.error as exc:
        raise EmailSyncError(f"Error en {address}: {exc}") from exc
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def _matching_invoice_pdfs(msg: Message) -> list[tuple[str, str, bytes]]:
    subject = decode_mime_header(msg.get("Subject"))
    matching: list[tuple[str, str, bytes]] = []
    for filename, pdf_bytes in extract_pdf_attachments(msg):
        text = extract_text_from_pdf(pdf_bytes)
        if (
            text
            and is_invoice_for_recipient(text)
            and is_purchase_invoice(text, subject)
        ):
            matching.append((text, filename, pdf_bytes))
    return matching


def _parse_message(
    mailbox: str, uid: str, msg: Message, pdf_items: list[tuple[str, str, bytes]]
) -> dict | None:
    subject = decode_mime_header(msg.get("Subject"))
    from_header = decode_mime_header(msg.get("From"))
    received_at = format_received_date(msg.get("Date"))

    pdf_texts = [item[0] for item in pdf_items]
    parsed = parse_invoice_email(
        uid=f"{mailbox.lower()}:{uid}",
        mailbox=mailbox,
        subject=subject,
        from_header=from_header,
        pdf_texts=pdf_texts,
        received_at=received_at,
    )
    if not parsed:
        return None

    # Guardar el PDF principal (el primero que coincide)
    _, pdf_name, pdf_bytes = pdf_items[0]
    parsed["pdf_original_name"] = pdf_name
    parsed["pdf_bytes"] = pdf_bytes
    return parsed
