import email
import imaplib
from email.message import Message

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
    """
    Lee TODOS los correos de todas las cuentas configuradas, en modo solo lectura.
    """
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

    all_invoices: list[dict] = []
    total_scanned = 0
    total_pdfs = 0
    accounts_ok: list[str] = []

    for account in EMAIL_ACCOUNTS:
        address = account["address"]
        password = account["password"]
        if not password:
            raise EmailSyncError(
                f"Falta contraseña para {address}. "
                "Añade EMAIL_PASSWORD en .env o inclúyela en EMAIL_ACCOUNTS."
            )

        result = _fetch_account(address, password)
        all_invoices.extend(result["invoices"])
        total_scanned += result["scanned"]
        total_pdfs += result["pdfs_checked"]
        accounts_ok.append(address)

    return {
        "invoices": all_invoices,
        "scanned": total_scanned,
        "pdfs_checked": total_pdfs,
        "accounts": accounts_ok,
    }


def _fetch_account(address: str, password: str) -> dict:
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    scanned = 0
    pdfs_checked = 0
    invoices: list[dict] = []

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

            matching_pdfs = _matching_invoice_pdfs(msg)
            pdfs_checked += len(extract_pdf_attachments(msg))

            if not matching_pdfs:
                continue

            parsed = _parse_message(address, uid_str, msg, matching_pdfs)
            if parsed:
                invoices.append(parsed)

        return {
            "invoices": invoices,
            "scanned": scanned,
            "pdfs_checked": pdfs_checked,
        }
    except imaplib.IMAP4.error as exc:
        raise EmailSyncError(f"Error en {address}: {exc}") from exc
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def _matching_invoice_pdfs(msg: Message) -> list[str]:
    subject = decode_mime_header(msg.get("Subject"))
    matching: list[str] = []
    for _filename, pdf_bytes in extract_pdf_attachments(msg):
        text = extract_text_from_pdf(pdf_bytes)
        if (
            text
            and is_invoice_for_recipient(text)
            and is_purchase_invoice(text, subject)
        ):
            matching.append(text)
    return matching


def _parse_message(
    mailbox: str, uid: str, msg: Message, pdf_texts: list[str]
) -> dict | None:
    subject = decode_mime_header(msg.get("Subject"))
    from_header = decode_mime_header(msg.get("From"))
    received_at = format_received_date(msg.get("Date"))

    return parse_invoice_email(
        uid=f"{mailbox.lower()}:{uid}",
        mailbox=mailbox,
        subject=subject,
        from_header=from_header,
        pdf_texts=pdf_texts,
        received_at=received_at,
    )
