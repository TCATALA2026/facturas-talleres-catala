import os

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

import config
import database
from email_client import EmailSyncError, fetch_invoices_from_mailbox
from scheduler import start_scheduler

app = Flask(__name__, static_folder="static")

# Migrar BD antigua a carpeta persistente
_old_db = config.BASE_DIR / "facturas.db"
if _old_db.exists() and not config.DATABASE_PATH.exists():
    import shutil
    shutil.copy2(_old_db, config.DATABASE_PATH)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.before_request
def setup():
    database.init_db()
    if request.method == "OPTIONS":
        return Response("", status=204)


@app.route("/api/config")
def api_config():
    return jsonify(
        {
            "recipient_name": config.RECIPIENT_NAME,
            "email_addresses": config.EMAIL_ADDRESSES,
            "configured": bool(
                config.EMAIL_ACCOUNTS
                and all(a["password"] for a in config.EMAIL_ACCOUNTS)
                and config.RECIPIENT_NAME
            ),
        }
    )


@app.route("/api/years")
def api_years():
    years = database.get_available_years()
    return jsonify({"years": years or [2026]})


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(
        app.static_folder,
        "manifest.json",
        mimetype="application/manifest+json",
    )


@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")


@app.route("/")
def index():
    invoices = database.get_all_invoices()
    summary = database.get_summary()
    configured = bool(
        config.EMAIL_ACCOUNTS
        and all(a["password"] for a in config.EMAIL_ACCOUNTS)
        and config.RECIPIENT_NAME
    )
    return render_template(
        "index.html",
        invoices=invoices,
        summary=summary,
        configured=configured,
        email_addresses=config.EMAIL_ADDRESSES,
        recipient_name=config.RECIPIENT_NAME,
    )


@app.route("/api/invoices")
def api_invoices():
    return jsonify(
        {
            "invoices": database.get_all_invoices(),
            "summary": database.get_summary(),
        }
    )


@app.route("/api/sync", methods=["POST"])
def api_sync():
    try:
        result = fetch_invoices_from_mailbox()
        new_count = 0
        for invoice in result["invoices"]:
            if database.upsert_invoice(invoice):
                new_count += 1
        return jsonify(
            {
                "ok": True,
                "scanned": result["scanned"],
                "pdfs_checked": result["pdfs_checked"],
                "invoices_found": len(result["invoices"]),
                "accounts": result.get("accounts", []),
                "new": new_count,
                "summary": database.get_summary(),
                "invoices": database.get_all_invoices(),
            }
        )
    except EmailSyncError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/trimestres")
def trimestres():
    years = database.get_available_years()
    year = request.args.get("year", type=int) or (years[0] if years else 2026)
    report = database.get_quarterly_report(year)
    return render_template(
        "trimestres.html",
        report=report,
        years=years or [year],
        selected_year=year,
        recipient_name=config.RECIPIENT_NAME,
    )


@app.route("/api/trimestres")
def api_trimestres():
    year = request.args.get("year", type=int) or 2026
    return jsonify(database.get_quarterly_report(year))


@app.route("/api/export/trimestres.csv")
def export_trimestres_csv():
    year = request.args.get("year", type=int) or 2026
    rows = database.get_quarterly_csv_rows(year)
    lines = ["Trimestre,Fecha,Proveedor,Nº Factura,Importe (€),Cuenta,Asunto"]
    for row in rows:
        subject = (row["asunto"] or "").replace('"', '""')
        lines.append(
            f'{row["trimestre"]},{row["fecha"]},{row["proveedor"]},'
            f'{row["numero_factura"]},{row["importe"]},{row["cuenta"]},"{subject}"'
        )
    content = "\n".join(lines)
    return Response(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=facturas_{year}_trimestres.csv"
        },
    )


@app.route("/api/cron/sync")
def cron_sync():
    """Para servicios externos (cron-job.org) que mantienen el servidor activo."""
    secret = os.getenv("CRON_SECRET", "")
    if secret and request.headers.get("X-Cron-Secret") != secret:
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    try:
        result = fetch_invoices_from_mailbox()
        new_count = sum(1 for inv in result["invoices"] if database.upsert_invoice(inv))
        return jsonify({"ok": True, "new": new_count, "scanned": result["scanned"]})
    except EmailSyncError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/invoices/<int:invoice_id>/status", methods=["PATCH"])
def api_update_status(invoice_id: int):
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if not status or not database.update_status(invoice_id, status):
        return jsonify({"ok": False, "error": "Estado no válido"}), 400
    return jsonify({"ok": True, "invoices": database.get_all_invoices()})


if __name__ == "__main__":
    database.init_db()
    start_scheduler()
    app.run(host="0.0.0.0", port=5000, debug=True)
else:
    database.init_db()
    start_scheduler()
