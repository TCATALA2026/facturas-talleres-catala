import sqlite3
from datetime import date, datetime
from typing import Any

from config import DATABASE_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_uid TEXT UNIQUE,
                mailbox TEXT,
                supplier TEXT NOT NULL,
                amount REAL,
                currency TEXT DEFAULT 'EUR',
                due_date TEXT,
                invoice_date TEXT,
                invoice_number TEXT,
                subject TEXT,
                received_at TEXT,
                status TEXT DEFAULT 'pending',
                is_expense INTEGER DEFAULT 1,
                source TEXT DEFAULT 'email',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        try:
            conn.execute("ALTER TABLE invoices ADD COLUMN mailbox TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE invoices ADD COLUMN invoice_date TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE invoices ADD COLUMN is_expense INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE invoices ADD COLUMN pdf_filename TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE invoices ADD COLUMN pdf_original_name TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()


def upsert_invoice(data: dict[str, Any]) -> bool:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM invoices WHERE email_uid = ?",
            (data["email_uid"],),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE invoices SET
                    supplier = ?,
                    amount = COALESCE(?, amount),
                    due_date = COALESCE(?, due_date),
                    invoice_date = COALESCE(?, invoice_date),
                    invoice_number = COALESCE(?, invoice_number),
                    subject = ?,
                    mailbox = COALESCE(?, mailbox),
                    is_expense = ?,
                    pdf_filename = COALESCE(?, pdf_filename),
                    pdf_original_name = COALESCE(?, pdf_original_name)
                WHERE email_uid = ?
                """,
                (
                    data["supplier"],
                    data.get("amount"),
                    data.get("due_date"),
                    data.get("invoice_date"),
                    data.get("invoice_number"),
                    data.get("subject"),
                    data.get("mailbox"),
                    1 if data.get("is_expense", True) else 0,
                    data.get("pdf_filename"),
                    data.get("pdf_original_name"),
                    data["email_uid"],
                ),
            )
            conn.commit()
            return False

        conn.execute(
            """
            INSERT INTO invoices (
                email_uid, mailbox, supplier, amount, currency, due_date,
                invoice_date, invoice_number, subject, received_at, status,
                is_expense, source, pdf_filename, pdf_original_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["email_uid"],
                data.get("mailbox"),
                data["supplier"],
                data.get("amount"),
                data.get("currency", "EUR"),
                data.get("due_date"),
                data.get("invoice_date"),
                data.get("invoice_number"),
                data.get("subject"),
                data.get("received_at"),
                data.get("status", "pending"),
                1 if data.get("is_expense", True) else 0,
                data.get("source", "email"),
                data.get("pdf_filename"),
                data.get("pdf_original_name"),
            ),
        )
        conn.commit()
        return True


def get_all_invoices(expenses_only: bool = True) -> list[dict[str, Any]]:
    with get_connection() as conn:
        if expenses_only:
            query = """
                SELECT * FROM invoices
                WHERE is_expense = 1 OR is_expense IS NULL
                ORDER BY
                    CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
                    due_date ASC,
                    supplier ASC
            """
        else:
            query = """
                SELECT * FROM invoices
                ORDER BY
                    CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
                    due_date ASC,
                    supplier ASC
            """
        rows = conn.execute(query).fetchall()
        return [_row_to_dict(row) for row in rows]


def _expense_filter_sql() -> str:
    return "AND (is_expense = 1 OR is_expense IS NULL)"


def get_summary(expenses_only: bool = True) -> dict[str, Any]:
    today = date.today().isoformat()
    expense_clause = _expense_filter_sql() if expenses_only else ""

    with get_connection() as conn:
        total_pending = conn.execute(
            f"""
            SELECT COUNT(*) as count, COALESCE(SUM(amount), 0) as total
            FROM invoices WHERE status = 'pending' {expense_clause}
            """
        ).fetchone()

        overdue = conn.execute(
            f"""
            SELECT COUNT(*) as count, COALESCE(SUM(amount), 0) as total
            FROM invoices
            WHERE status = 'pending' AND due_date IS NOT NULL AND due_date < ?
            {expense_clause}
            """,
            (today,),
        ).fetchone()

        due_soon = conn.execute(
            f"""
            SELECT COUNT(*) as count, COALESCE(SUM(amount), 0) as total
            FROM invoices
            WHERE status = 'pending'
              AND due_date IS NOT NULL
              AND due_date >= ?
              AND due_date <= date(?, '+7 days')
            {expense_clause}
            """,
            (today, today),
        ).fetchone()

    return {
        "pending_count": total_pending["count"],
        "pending_total": round(total_pending["total"] or 0, 2),
        "overdue_count": overdue["count"],
        "overdue_total": round(overdue["total"] or 0, 2),
        "due_soon_count": due_soon["count"],
        "due_soon_total": round(due_soon["total"] or 0, 2),
    }


def get_invoice(invoice_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None


def update_status(invoice_id: int, status: str) -> bool:
    if status not in ("pending", "paid", "cancelled"):
        return False
    with get_connection() as conn:
        conn.execute(
            "UPDATE invoices SET status = ? WHERE id = ?",
            (status, invoice_id),
        )
        conn.commit()
        return conn.total_changes > 0


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["status_label"] = _status_label(d.get("status"), d.get("due_date"))
    d["fiscal_date"] = _fiscal_date(d)
    d["year"], d["quarter"] = _year_quarter(d["fiscal_date"])
    d["quarter_label"] = _quarter_label(d["year"], d["quarter"])
    d["has_pdf"] = bool(d.get("pdf_filename"))
    return d


def _fiscal_date(inv: dict[str, Any]) -> str | None:
    if inv.get("invoice_date"):
        return inv["invoice_date"]
    received = inv.get("received_at") or ""
    if len(received) >= 10:
        return received[:10]
    return None


def _year_quarter(date_str: str | None) -> tuple[int | None, int | None]:
    if not date_str:
        return None, None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        if d.year < 2000 or d.year > 2100:
            return None, None
        return d.year, (d.month - 1) // 3 + 1
    except ValueError:
        return None, None


def _quarter_label(year: int | None, quarter: int | None) -> str:
    if not year or not quarter:
        return "Sin fecha"
    names = {1: "1T (Ene–Mar)", 2: "2T (Abr–Jun)", 3: "3T (Jul–Sep)", 4: "4T (Oct–Dic)"}
    return f"{year} {names[quarter]}"


def get_available_years() -> list[int]:
    years: set[int] = set()
    for inv in get_all_invoices():
        y = inv.get("year")
        if y and 2000 <= y <= 2100:
            years.add(y)
    return sorted(years, reverse=True)


def get_quarterly_report(year: int) -> dict[str, Any]:
    quarters = {
        1: {"label": "1T — Enero a Marzo", "invoices": [], "count": 0, "total": 0.0},
        2: {"label": "2T — Abril a Junio", "invoices": [], "count": 0, "total": 0.0},
        3: {"label": "3T — Julio a Septiembre", "invoices": [], "count": 0, "total": 0.0},
        4: {"label": "4T — Octubre a Diciembre", "invoices": [], "count": 0, "total": 0.0},
    }

    for inv in get_all_invoices():
        if inv.get("year") != year or not inv.get("quarter"):
            continue
        q = inv["quarter"]
        quarters[q]["invoices"].append(inv)
        quarters[q]["count"] += 1
        if inv.get("amount"):
            quarters[q]["total"] += inv["amount"]

    for q in quarters.values():
        q["total"] = round(q["total"], 2)
        q["invoices"].sort(key=lambda i: i.get("fiscal_date") or "")

    year_total = round(sum(q["total"] for q in quarters.values()), 2)
    year_count = sum(q["count"] for q in quarters.values())

    return {
        "year": year,
        "quarters": quarters,
        "year_total": year_total,
        "year_count": year_count,
    }


def get_quarterly_csv_rows(year: int) -> list[dict[str, Any]]:
    report = get_quarterly_report(year)
    rows: list[dict[str, Any]] = []
    for q_num in (1, 2, 3, 4):
        q = report["quarters"][q_num]
        for inv in q["invoices"]:
            rows.append(
                {
                    "trimestre": f"{year}-T{q_num}",
                    "fecha": inv.get("fiscal_date") or "",
                    "proveedor": inv.get("supplier") or "",
                    "numero_factura": inv.get("invoice_number") or "",
                    "importe": inv.get("amount") or "",
                    "cuenta": inv.get("mailbox") or "",
                    "asunto": inv.get("subject") or "",
                }
            )
    return rows


def _status_label(status: str | None, due_date: str | None) -> str:
    if status == "paid":
        return "Pagada"
    if status == "cancelled":
        return "Anulada"
    if due_date:
        try:
            due = datetime.strptime(due_date, "%Y-%m-%d").date()
            today = date.today()
            if due < today:
                return "Vencida"
            if (due - today).days <= 7:
                return "Vence pronto"
        except ValueError:
            pass
    return "Pendiente"
