"""
WashAI web API (Flask).
Run locally:   python app.py          -> http://127.0.0.1:5000
Production:    gunicorn app:app
"""
import os
from datetime import date

from flask import Flask, jsonify, request, send_from_directory

import washai

ADMIN_KEY = os.environ.get("ADMIN_KEY", "demo")   # change it when you deploy!
app = Flask(__name__, static_folder="static")


# ----------------------------------------------------------------- startup
def bootstrap():
    conn = washai.connect()
    washai.init_db(conn)
    if conn.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == 0:
        washai.seed_demo(conn)          # demo data so the forecast has history
    conn.close()


bootstrap()


# ----------------------------------------------------------------- helpers
def db():
    return washai.connect()


def is_admin():
    return request.headers.get("X-Admin-Key") == ADMIN_KEY


def need_admin():
    return jsonify(error="هذا الإجراء للإدارة فقط"), 401


def rows(cursor_rows):
    return [dict(r) for r in cursor_rows]


# ------------------------------------------------------------------- pages
@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True)


# ---------------------------------------------------------------- customer
@app.get("/api/services")
def services():
    conn = db()
    data = rows(conn.execute("SELECT name, price FROM services ORDER BY price"))
    conn.close()
    return jsonify(data)


@app.get("/api/track")
def track():
    """Customer tracks an order. Needs order id AND phone, so ids can't be guessed."""
    order_id = request.args.get("order_id", type=int)
    phone = request.args.get("phone", "").strip()
    conn = db()
    o = conn.execute(
        "SELECT o.id, o.status, o.total, o.due_at, c.name FROM orders o "
        "JOIN customers c ON c.id=o.customer_id WHERE o.id=? AND c.phone=?",
        (order_id, phone)).fetchone()
    if o is None:
        conn.close()
        return jsonify(error="ما لقينا طلب بهذي البيانات"), 404
    history = rows(conn.execute(
        "SELECT status, changed_at FROM status_log WHERE order_id=? ORDER BY id", (order_id,)))
    conn.close()
    return jsonify(order=dict(o), history=history)


@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    phone = str(data.get("phone", "")).strip()
    message = str(data.get("message", "")).strip()
    if not message:
        return jsonify(error="اكتب رسالتك"), 400
    conn = db()
    c = conn.execute("SELECT id FROM customers WHERE phone=?", (phone,)).fetchone()
    reply = washai.chatbot(conn, c["id"] if c else -1, message)
    conn.close()
    return jsonify(reply=reply)


# ------------------------------------------------------------------- admin
@app.post("/api/orders")
def new_order():
    if not is_admin():
        return need_admin()
    data = request.get_json(silent=True) or {}
    name, phone = str(data.get("name", "")).strip(), str(data.get("phone", "")).strip()
    pieces = data.get("pieces", {})
    if not name or not phone or not isinstance(pieces, dict) or not pieces:
        return jsonify(error="الاسم والجوال والقطع مطلوبة"), 400
    conn = db()
    try:
        pieces = {str(k): int(v) for k, v in pieces.items() if int(v) > 0}
        if not pieces:
            return jsonify(error="اختر قطعة وحدة على الأقل"), 400
        cid = washai.add_customer(conn, name, phone)
        order_id, codes = washai.create_order(conn, cid, pieces)
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    finally:
        conn.close()
    return jsonify(order_id=order_id, qr_codes=codes), 201


@app.post("/api/orders/<int:order_id>/advance")
def advance(order_id):
    if not is_admin():
        return need_admin()
    conn = db()
    if conn.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone() is None:
        conn.close()
        return jsonify(error="الطلب غير موجود"), 404
    status = washai.advance_order(conn, order_id)
    conn.close()
    return jsonify(order_id=order_id, status=status)


@app.get("/api/scan/<code>")
def scan(code):
    if not is_admin():
        return need_admin()
    conn = db()
    r = washai.scan_qr(conn, code)
    conn.close()
    if r is None:
        return jsonify(error="الرمز غير موجود"), 404
    return jsonify(dict(r))


@app.get("/api/forecast")
def forecast():
    if not is_admin():
        return need_admin()
    conn = db()
    preds = washai.forecast(conn, date.today(), days=7)
    mae_model, mae_naive = washai.backtest(conn)
    conn.close()
    plan = washai.staffing_plan(preds)
    for p in plan:
        p["day"] = p["day"].isoformat()
    return jsonify(plan=plan, mae_model=round(mae_model, 2), mae_naive=round(mae_naive, 2))


@app.get("/api/reports/<name>")
def report(name):
    if not is_admin():
        return need_admin()
    conn = db()
    try:
        data = rows(washai.run_report(conn, name))
    except KeyError:
        conn.close()
        return jsonify(error="تقرير غير معروف"), 404
    conn.close()
    return jsonify(data)


if __name__ == "__main__":
    app.run(debug=True)
