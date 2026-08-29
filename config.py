import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Carpeta persistente (Render/cloud monta volumen en /app/data)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.servidor-correo.net")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))

RECIPIENT_NAME = os.getenv("RECIPIENT_NAME", "")

# Si false, la app funciona solo con subida manual de PDFs (sin Hostalia)
EMAIL_SYNC_ENABLED = os.getenv("EMAIL_SYNC_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

DATABASE_PATH = BASE_DIR / "data" / "facturas.db"
PDF_DIR = DATA_DIR / "pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

# Contraseña compartida (si ambas cuentas usan la misma)
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")


def _parse_email_accounts() -> list[dict[str, str]]:
    """
    Formatos soportados en EMAIL_ACCOUNTS:
      - cuenta1@dominio.com,cuenta2@dominio.com  (+ EMAIL_PASSWORD compartida)
      - cuenta1@dominio.com:pass1,cuenta2@dominio.com:pass2
    También admite EMAIL_ADDRESS legacy para una sola cuenta.
    """
    raw = os.getenv("EMAIL_ACCOUNTS", "").strip()
    accounts: list[dict[str, str]] = []

    if raw:
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                address, password = entry.split(":", 1)
                accounts.append(
                    {"address": address.strip(), "password": password.strip()}
                )
            else:
                accounts.append({"address": entry, "password": EMAIL_PASSWORD})
    elif os.getenv("EMAIL_ADDRESS", "").strip():
        accounts.append(
            {
                "address": os.getenv("EMAIL_ADDRESS", "").strip(),
                "password": EMAIL_PASSWORD,
            }
        )

    return accounts


EMAIL_ACCOUNTS = _parse_email_accounts()
EMAIL_ADDRESSES = [a["address"] for a in EMAIL_ACCOUNTS]
