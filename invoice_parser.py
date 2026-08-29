import io
import re
from datetime import datetime
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

import pdfplumber

from config import RECIPIENT_NAME

INVOICE_MARKERS = [
    r"\bfactura\b",
    r"\binvoice\b",
    r"\bfacturación\b",
    r"\bfacturacion\b",
    r"\btotal\b",
    r"\biva\b",
    r"\bnif\b",
    r"\bcif\b",
    r"\bdni\b",
    r"\bbase\s+imponible\b",
    r"\bimporte\b",
    r"\bsubtotal\b",
]

# Totales etiquetados (prioridad alta)
LABELED_TOTAL_PATTERNS = [
    r"(?:total\s+(?:factura|a\s+pagar|documento|general|facturado|con\s+iva)|importe\s+total|total\s+importe|total\s+euros?|total\s+eur|amount\s+due|total\s+due|total\s+a\s+abonar)\s*[:\s]*(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2})?)",
    r"(?:total)\s*[:\s]*(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2})?)\s*(?:€|eur|euros?)",
]

AMOUNT_PATTERNS = [
    r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2})?)\s*(?:€|eur|euros?)",
    r"(?:€|eur)\s*(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2})?)",
]

BASE_IVA_PATTERNS = [
    (r"(?:base\s+imponible|base\s+imp\.|subtotal|importe\s+neto)\s*[:\s]*(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2})?)", "base"),
    (r"(?:iva|i\.v\.a\.|impuesto\s+valor\s+añadido)(?:\s*\(?\d{1,2}\s*%?\)?)?\s*[:\s]*(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2})?)", "iva"),
]

DUE_DATE_PATTERNS = [
    r"(?:fecha\s+de\s+vencimiento|vencimiento|fecha\s+l[ií]mite|due\s+date|pago\s+hasta|fecha\s+de\s+pago)\s*[:\s]*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
    r"(?:fecha\s+de\s+vencimiento|vencimiento|due\s+date)\s*[:\s]*(\d{1,2}\s+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?\d{4})",
]

INVOICE_DATE_PATTERNS = [
    r"(?:fecha\s+(?:de\s+)?(?:factura|emisi[oó]n|expedici[oó]n)|fecha\s+factura|date\s+of\s+invoice|invoice\s+date|emitida?\s+(?:el|en)|expedida?\s+(?:el|en))\s*[:\s]*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
    r"(?:fecha\s+(?:de\s+)?(?:factura|emisi[oó]n))\s*[:\s]*(\d{1,2}\s+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?\d{4})",
    r"(?:factura|invoice)\s+(?:del|de|date|n[ºo°]?\.?\s*[A-Z0-9\-]+.*?del)?\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
    r"(?:^|\n)\s*fecha\s*[:\s]*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
    r"(\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2})",
]

SUBJECT_DATE_PATTERNS = [
    r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})",
    r"(?:nomina|nómina|recibo|factura)\s+(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s*/?\s*(\d{4})",
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s*/?\s*(\d{4})",
]

INVOICE_NUMBER_PATTERNS = [
    r"(?:n[úu]mero\s+de\s+factura|n[ºo°]\s*factura|factura\s+n[ºo°]|invoice\s+(?:no|number|#)|factura\s*#)\s*[:\s]*([A-Z0-9\-/]+)",
    r"(?:factura|fra\.?|invoice)\s*[:\s#]*([A-Z0-9\-/]{3,})",
    r"\b(FV\d{6,}|L\d{6,}|F[A-Z]?\d{4,}|[A-Z]{1,3}\d{5,})\b",
]

SUBJECT_NUMBER_PATTERNS = [
    r"FACTURA\s+(FV\d+)",
    r"NUMERO\s+DE\s+FACTURA\s+(L\d+)",
    r"\bFRA\.?\s*(\d+)\b",
    r"\b(O\d{2}-\d+)\b",
    r"Factura_N\*?_(\d{4}-\d+-\d+)",
]

# Documentos que NO son facturas de gasto (las que tú pagas a proveedores)
EXCLUDE_PATTERNS = [
    r"comprobante\s+transferencia",
    r"presupuesto",
    r"\bn[oó]mina",
    r"certificat",
    r"documento\s+firmado",
    r"transferencia\s+ordinaria",
    r"solicitud\s+(?:denegada|subsan)",
    r"aviso\s+importante",
    r"documentaci[oó]n\s+de\s+tu\s+seguro",
    r"p[oó]liza",
    r"pago\s+aceptado",
    r"facturas?\s+de\s+venta",
    r"env[ií]o\s+de\s+facturas\s+de\s+venta",
    r"\balbar[aá]n",
    r"modelo\s+036",
    r"compensaci[oó]n\s+de\s+facturas",
    r"cambio\s+integral",
    r"duplicado\s+de\s+factura",
    r"generaci[oó]n\s+de\s+certificado",
    r"declaraciones\s+(?:segundo|tercer|primer)\s+trimestre",
    r"documentaci[oó]n\s+relativa\s+al\s+trabajo",
    r"informacion\s+sobre\s+su\s+factura",  # often copies of sales invoices
]

# Indicios de factura de compra en asunto
PURCHASE_SUBJECT_PATTERNS = [
    r"\bfactura",
    r"\bfra\.?\s*\d",
    r"n/factura",
    r"nº?\s*factura",
    r"tu\s+factura",
    r"su\s+factura",
    r"invoice",
    r"facturaci[oó]n",
]

MONTHS_ES = {
    "enero": 1, "feb": 1,
    "febrero": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "sep": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}


def _month_number(name: str) -> int | None:
    key = name.lower().strip()
    return MONTHS_ES.get(key) or MONTHS_ES.get(key[:3])


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                decoded.append(part.decode("utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def extract_text_from_pdf(data: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return ""


def extract_pdf_attachments(msg: Message) -> list[tuple[str, bytes]]:
    pdfs: list[tuple[str, bytes]] = []
    for part in _walk_message_parts(msg):
        filename = part.get_filename()
        content_type = part.get_content_type()
        is_pdf = (
            (filename and filename.lower().endswith(".pdf"))
            or content_type == "application/pdf"
        )
        if not is_pdf:
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes) and payload:
            name = decode_mime_header(filename) if filename else "adjunto.pdf"
            pdfs.append((name, payload))
    return pdfs


def is_invoice_for_recipient(text: str) -> bool:
    if not text or len(text.strip()) < 40:
        return False

    lower = text.lower()
    marker_hits = sum(
        1 for pattern in INVOICE_MARKERS if re.search(pattern, lower, re.IGNORECASE)
    )
    if marker_hits < 2:
        return False

    if not RECIPIENT_NAME:
        return False

    name_parts = [
        part.strip().lower()
        for part in re.split(r"[\s,]+", RECIPIENT_NAME)
        if len(part.strip()) >= 3
    ]
    if not name_parts:
        return False

    matched_parts = sum(1 for part in name_parts if part in lower)
    required = max(1, len(name_parts) // 2 + len(name_parts) % 2)
    return matched_parts >= required


def is_purchase_invoice(text: str, subject: str = "") -> bool:
    """
    True si es una factura de GASTO: un proveedor te cobra a ti.
    Excluye nóminas, presupuestos, transferencias, facturas de venta tuyas, etc.
    """
    combined = f"{subject}\n{text}".lower()

    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return False

    if _is_issuer_not_buyer(text):
        return False

    for pattern in PURCHASE_SUBJECT_PATTERNS:
        if re.search(pattern, subject, re.IGNORECASE):
            return True

    if _is_client_in_pdf(text):
        return True

    # PDF con marcadores de factura y tu nombre como cliente
    if text and is_invoice_for_recipient(text):
        return True

    return False


def _is_issuer_not_buyer(text: str) -> bool:
    """Detecta si Talleres Catala aparece como emisor (factura de venta propia)."""
    if not text or not RECIPIENT_NAME:
        return False
    lower = text.lower()
    name_parts = [p for p in re.split(r"[\s,]+", RECIPIENT_NAME.lower()) if len(p) >= 4]
    if not name_parts:
        return False

    issuer_patterns = [
        r"(?:emisor|vendedor|expedidor|proveedor|raz[oó]n\s+social\s+del\s+emisor)",
    ]
    for part in name_parts[:2]:
        for ip in issuer_patterns:
            if re.search(rf"{ip}.{{0,150}}{re.escape(part)}", lower, re.DOTALL):
                return True
            if re.search(rf"{re.escape(part)}.{{0,80}}{ip}", lower, re.DOTALL):
                return True
    return False


def _is_client_in_pdf(text: str) -> bool:
    """Tu empresa aparece como cliente / destinatario de la factura."""
    if not text or not RECIPIENT_NAME:
        return False
    lower = text.lower()
    name_parts = [p for p in re.split(r"[\s,]+", RECIPIENT_NAME.lower()) if len(p) >= 4]
    if not name_parts:
        return False

    client_patterns = [
        r"(?:cliente|destinatario|facturar\s+a|comprador|titular|datos\s+del\s+cliente)",
    ]
    for cp in client_patterns:
        match = re.search(rf"{cp}.{{0,200}}", lower, re.DOTALL)
        if match and any(p in match.group(0) for p in name_parts):
            return True
    return False


def _walk_message_parts(msg: Message):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() != "multipart":
                yield part
    else:
        yield msg


def parse_amount(text: str) -> float | None:
    # 1. Totales etiquetados (el último suele ser el definitivo)
    labeled: list[float] = []
    for pattern in LABELED_TOTAL_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            val = _normalize_amount(match.group(1))
            if val and 1 <= val <= 1_000_000:
                labeled.append(val)
    if labeled:
        return labeled[-1]

    # 2. Base imponible + IVA
    base_val = iva_val = None
    for pattern, kind in BASE_IVA_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = _normalize_amount(match.group(1))
            if val:
                if kind == "base":
                    base_val = val
                else:
                    iva_val = val
    if base_val and iva_val:
        return round(base_val + iva_val, 2)
    if base_val and not iva_val:
        iva_pct = re.search(r"iva\s*(?:\(?(\d{1,2})\s*%", text, re.IGNORECASE)
        if iva_pct:
            pct = int(iva_pct.group(1))
            return round(base_val * (1 + pct / 100), 2)

    # 3. Cualquier importe con € (filtrar razonables)
    amounts: list[float] = []
    for pattern in AMOUNT_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            val = _normalize_amount(match.group(1))
            if val and 5 <= val <= 500_000:
                amounts.append(val)
    if amounts:
        # Preferir el mayor razonable pero no outliers absurdos
        amounts.sort()
        return amounts[-1]

    return None


def parse_due_date(text: str) -> str | None:
    return _first_date_match(text, DUE_DATE_PATTERNS)


def parse_invoice_date(text: str, subject: str = "") -> str | None:
    found = _first_date_match(text, INVOICE_DATE_PATTERNS)
    if found:
        return found
    return _parse_date_from_subject(subject)


def parse_invoice_number(text: str, subject: str = "") -> str | None:
    for pattern in SUBJECT_NUMBER_PATTERNS:
        match = re.search(pattern, subject, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    for pattern in INVOICE_NUMBER_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            num = match.group(1).strip()
            if num.lower() not in ("ura", "tura", "actura"):
                return num
    return None


def supplier_from_sender(from_header: str) -> str:
    name, email_addr = parseaddr(from_header)
    if name and name != email_addr:
        return name.strip()
    if email_addr and "@" in email_addr:
        domain = email_addr.split("@")[1]
        return domain.split(".")[0].capitalize()
    return from_header or "Proveedor desconocido"


def parse_invoice_email(
    uid: str,
    subject: str,
    from_header: str,
    pdf_texts: list[str],
    received_at: str,
    mailbox: str = "",
) -> dict[str, Any]:
    pdf_text = "\n".join(pdf_texts)
    combined_text = "\n".join([subject, pdf_text])
    supplier = supplier_from_sender(from_header)

    amount = parse_amount(combined_text)
    due_date = parse_due_date(combined_text)
    invoice_date = parse_invoice_date(combined_text, subject)
    invoice_number = parse_invoice_number(combined_text, subject)

    return {
        "email_uid": uid,
        "mailbox": mailbox,
        "supplier": supplier,
        "amount": amount,
        "currency": "EUR",
        "due_date": due_date,
        "invoice_date": invoice_date,
        "invoice_number": invoice_number,
        "subject": subject,
        "received_at": received_at,
        "status": "pending",
        "is_expense": True,
        "source": "email",
    }


def _first_date_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw = match.group(1)
            if re.match(r"\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}", raw):
                parsed = _parse_iso_date(raw)
            else:
                parsed = _parse_date_string(raw)
            if parsed:
                return parsed
    return None


def _parse_date_from_subject(subject: str) -> str | None:
    if not subject:
        return None

    match = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", subject)
    if match:
        d, m, y = match.groups()
        y = y if len(y) == 4 else f"20{y}"
        return _parse_date_string(f"{d}/{m}/{y}")

    match = re.search(
        r"(?:nomina|nómina|recibo|factura)\s+(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s*/?\s*(\d{4})",
        subject,
        re.IGNORECASE,
    )
    if match:
        month_name, year = match.groups()
        month = _month_number(month_name)
        if month:
            return f"{year}-{month:02d}-01"

    match = re.search(
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s*/?\s*(\d{4})",
        subject,
        re.IGNORECASE,
    )
    if match:
        month_name, year = match.groups()
        month = _month_number(month_name)
        if month:
            return f"{year}-{month:02d}-01"

    return None


def _normalize_amount(raw: str) -> float | None:
    cleaned = raw.strip().replace(" ", "").replace("\u00a0", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        value = float(cleaned)
        return value if value > 0 else None
    except ValueError:
        return None


def _parse_iso_date(raw: str) -> str | None:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_date_string(raw: str) -> str | None:
    raw = raw.strip().lower()

    spanish_match = re.match(
        r"(\d{1,2})\s+(?:de\s+)?(\w+)\s+(?:de\s+)?(\d{4})",
        raw,
    )
    if spanish_match:
        day, month_name, year = spanish_match.groups()
        month = _month_number(month_name)
        if month:
            try:
                return datetime(int(year), month, int(day)).strftime("%Y-%m-%d")
            except ValueError:
                pass

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if parsed.year < 2000 or parsed.year > 2100:
                continue
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def format_received_date(msg_date: str | None) -> str:
    if not msg_date:
        return datetime.now().isoformat()
    try:
        return parsedate_to_datetime(msg_date).isoformat()
    except (TypeError, ValueError, IndexError):
        return datetime.now().isoformat()
