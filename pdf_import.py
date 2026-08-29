import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from config import RECIPIENT_NAME
from invoice_parser import (
    extract_text_from_pdf,
    is_invoice_for_recipient,
    is_purchase_invoice,
    parse_invoice_email,
)


class PdfImportError(Exception):
    pass


def parse_uploaded_pdf(pdf_bytes: bytes, filename: str) -> dict[str, Any]:
    if not pdf_bytes:
        raise PdfImportError("Archivo vacío")

    text = extract_text_from_pdf(pdf_bytes)
    if not text or len(text.strip()) < 20:
        raise PdfImportError("No se pudo leer el contenido del PDF")

    subject = filename.rsplit(".", 1)[0] if filename else "Factura"

    if RECIPIENT_NAME and not is_invoice_for_recipient(text):
        if not is_purchase_invoice(text, subject):
            raise PdfImportError(
                "No parece una factura de gasto a nombre de "
                f"{RECIPIENT_NAME or 'tu empresa'}"
            )
    elif not is_purchase_invoice(text, subject):
        raise PdfImportError("No parece una factura de gasto")

    digest = hashlib.sha256(pdf_bytes).hexdigest()[:24]
    uid = f"upload:{digest}"

    parsed = parse_invoice_email(
        uid=uid,
        mailbox="manual",
        subject=subject,
        from_header=filename,
        pdf_texts=[text],
        received_at=datetime.now(timezone.utc).isoformat(),
    )
    parsed["pdf_bytes"] = pdf_bytes
    parsed["pdf_original_name"] = filename if filename.lower().endswith(".pdf") else f"{filename}.pdf"
    parsed["source"] = "upload"
    return parsed
