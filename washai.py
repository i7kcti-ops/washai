"""
WashAI - smart laundry management (graduation project demo)
Pure Python 3 + SQLite. No external libraries needed.
"""
import math
import os
import random
import secrets
import sqlite3
import io
import base64
import qrcode
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = Path(os.environ.get("WASHAI_DB", HERE / "washai.db"))
FLOW = ["received", "washing", "ready", "delivered"]
ORDERS_PER_WORKER = 12          # how many orders one worker handles per day
DAY_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


# ---------------------------------------------------------------- database
def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    services = [("ثوب", 8), ("قميص", 5), ("بنطلون", 6), ("شماغ", 4),
                ("بشت", 35), ("لحاف", 25), ("فستان", 15)]
    conn.executemany("INSERT OR IGNORE INTO services(name, price) VALUES (?,?)", services)
    conn.executemany(
        "INSERT OR IGNORE INTO inventory(name, quantity, min_level) VALUES (?,?,?)",
        [("منظف", 40, 15), ("منعم", 12, 15), ("أكياس تغليف", 300, 100)])
    conn.commit()


# ------------------------------------------------------------------ orders
def add_customer(conn, name, phone):
    cur = conn.execute("INSERT OR IGNORE INTO customers(name, phone) VALUES (?,?)", (name, phone))
    conn.commit()
    return conn.execute("SELECT id FROM customers WHERE phone=?", (phone,)).fetchone()["id"]


def _log_and_notify(conn, order_id, status, when):
    conn.execute("INSERT INTO status_log(order_id, status, changed_at) VALUES (?,?,?)",
                 (order_id, status, when))
    o = conn.execute("SELECT o.customer_id, c.name FROM orders o "
                     "JOIN customers c ON c.id=o.customer_id WHERE o.id=?", (order_id,)).fetchone()
    msgs = {
        "received":  f"هلا {o['name']}، استلمنا ملابسك. رقم طلبك #{order_id}",
        "washing":   f"طلبك #{order_id} الحين في الغسيل",
        "ready":     f"أبشر، طلبك #{order_id} جاهز. تفضل استلمه",
        "delivered": f"تم تسليم طلبك #{order_id}. يعطيك العافية",
    }
    conn.execute("INSERT INTO notifications(customer_id, order_id, message, sent_at) VALUES (?,?,?,?)",
                 (o["customer_id"], order_id, msgs[status], when))


def create_order(conn, customer_id, pieces, created_at=None):
    """pieces = {"ثوب": 3, "قميص": 2}. Returns (order_id, [qr codes])."""
    # validate everything BEFORE writing, so a bad request never leaves a half-saved order
    services = {}
    for service_name in pieces:
        svc = conn.execute("SELECT id, price FROM services WHERE name=?", (service_name,)).fetchone()
        if svc is None:
            raise ValueError(f"خدمة غير موجودة: {service_name}")
        services[service_name] = svc

    created = created_at or datetime.now()
    due = created + timedelta(days=2)
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        cur = conn.execute("INSERT INTO orders(customer_id, created_at, due_at) VALUES (?,?,?)",
                           (customer_id, created.strftime(fmt), due.strftime(fmt)))
        order_id, total, codes = cur.lastrowid, 0.0, []
        for service_name, qty in pieces.items():
            svc = services[service_name]
            for _ in range(qty):
                code = "WA-" + secrets.token_hex(4).upper()      # one unique tag per piece
                conn.execute("INSERT INTO order_items(order_id, service_id, qr_code, price) VALUES (?,?,?,?)",
                             (order_id, svc["id"], code, svc["price"]))
                codes.append(code)
                total += svc["price"]
        conn.execute("UPDATE orders SET total=? WHERE id=?", (total, order_id))
        _log_and_notify(conn, order_id, "received", created.strftime(fmt))
        conn.commit()
    except Exception:
        conn.rollback()      # all-or-nothing
        raise
    return order_id, codes


def advance_order(conn, order_id):
    """Move the order to the next stage, log it, and notify the customer."""
    row = conn.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
    i = FLOW.index(row["status"])
    if i == len(FLOW) - 1:
        return row["status"]
    new = FLOW[i + 1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE orders SET status=? WHERE id=?", (new, order_id))
    _log_and_notify(conn, order_id, new, now)
    conn.commit()
    return new


def scan_qr(conn, code):
    """Scanning a tag tells staff which order and service the piece belongs to."""
    return conn.execute(
        "SELECT oi.qr_code, s.name AS service, o.id AS order_id, o.status, c.name AS customer "
        "FROM order_items oi JOIN services s ON s.id=oi.service_id "
        "JOIN orders o ON o.id=oi.order_id JOIN customers c ON c.id=o.customer_id "
        "WHERE oi.qr_code=?", (code,)).fetchone()


# ---------------------------------------------------------------- forecast
def daily_counts(conn, end_day, weeks):
    """Orders per day for the `weeks` weeks before end_day (zeros included)."""
    start = end_day - timedelta(days=weeks * 7)
    rows = conn.execute(
        "SELECT date(created_at) d, COUNT(*) n FROM orders "
        "WHERE date(created_at) >= ? AND date(created_at) < ? GROUP BY d",
        (start.isoformat(), end_day.isoformat())).fetchall()
    found = {r["d"]: r["n"] for r in rows}
    return {start + timedelta(days=k): found.get((start + timedelta(days=k)).isoformat(), 0)
            for k in range(weeks * 7)}


def forecast(conn, start_day, days=7, weeks=8, decay=0.8):
    """
    Weekday-seasonal weighted average.
    For each target day we average the same weekday in past weeks,
    giving recent weeks more weight (weight = decay ** weeks_ago).
    """
    history = daily_counts(conn, start_day, weeks)
    result = {}
    for k in range(days):
        target = start_day + timedelta(days=k)
        num = den = 0.0
        for w in range(1, weeks + 1):
            past = target - timedelta(days=7 * w)
            if past in history:
                weight = decay ** (w - 1)
                num += history[past] * weight
                den += weight
        result[target] = num / den if den else 0.0
    return result


def backtest(conn, test_days=28):
    """Compare our model with a naive baseline ('same as last week') on held-out days."""
    end = date.today()
    errs_model, errs_naive = [], []
    for k in range(test_days, 0, -1):
        day = end - timedelta(days=k)
        actual = conn.execute("SELECT COUNT(*) n FROM orders WHERE date(created_at)=?",
                              (day.isoformat(),)).fetchone()["n"]
        pred = forecast(conn, day, days=1)[day]
        naive = conn.execute("SELECT COUNT(*) n FROM orders WHERE date(created_at)=?",
                             ((day - timedelta(days=7)).isoformat(),)).fetchone()["n"]
        errs_model.append(abs(actual - pred))
        errs_naive.append(abs(actual - naive))
    return sum(errs_model) / test_days, sum(errs_naive) / test_days


def staffing_plan(preds):
    avg = sum(preds.values()) / len(preds)
    plan = []
    for day, p in preds.items():
        plan.append({
            "day": day, "name": DAY_AR[day.weekday()], "orders": round(p),
            "workers": max(1, math.ceil(p / ORDERS_PER_WORKER)),
            "peak": p > avg * 1.2,
        })
    return plan


# ----------------------------------------------------------------- chatbot
def chatbot(conn, customer_id, text):
    """Rule-based Saudi-dialect assistant. An LLM API can replace this later."""
    t = text.strip()
    if any(w in t for w in ("دوام", "تفتحون", "ساعات", "مواعيد")):
        return "نفتح من ٨ الصبح إلى ١٠ بالليل كل يوم."
    if any(w in t for w in ("بكم", "سعر", "أسعار", "اسعار", "تكلفة")):
        rows = conn.execute("SELECT name, price FROM services ORDER BY price").fetchall()
        return "أسعارنا: " + "، ".join(f"{r['name']} {r['price']:g} ريال" for r in rows)
    if any(w in t for w in ("وين", "حالة", "طلبي", "جاهز")):
        o = conn.execute("SELECT id, status, due_at FROM orders WHERE customer_id=? "
                         "ORDER BY id DESC LIMIT 1", (customer_id,)).fetchone()
        if not o:
            return "ما لقيت لك طلبات للحين."
        names = {"received": "استلمناه", "washing": "في الغسيل الحين",
                 "ready": "جاهز للاستلام", "delivered": "انسلّم لك"}
        return f"طلبك #{o['id']} {names[o['status']]}، والموعد المتوقع {o['due_at'][:10]}."
    return "ما فهمت عليك زين، تقدر تسأل عن حالة الطلب أو الأسعار أو الدوام."


# ----------------------------------------------------------------- reports
def run_report(conn, name):
    text = (HERE / "reports.sql").read_text(encoding="utf-8")
    for block in text.split("-- name:")[1:]:
        title, _, sql = block.partition("\n")
        if title.strip() == name:
            return conn.execute(sql).fetchall()
    raise KeyError(name)


# -------------------------------------------------------------------- demo
def seed_demo(conn, weeks=12, seed=42):
    """Generate fake history with a weekday pattern so the forecast has something to learn."""
    rnd = random.Random(seed)
    names = ["محمد", "عبدالله", "فهد", "سلطان", "نورة", "سارة", "خالد", "ريم", "ناصر", "منيرة"]
    ids = [add_customer(conn, n, f"05{rnd.randint(10000000, 99999999)}") for n in names]
    base = {0: 9, 1: 9, 2: 11, 3: 16, 4: 18, 5: 14, 6: 12}      # Mon..Sun
    today = date.today()
    for back in range(weeks * 7, 0, -1):
        day = today - timedelta(days=back)
        n = max(1, round(base[day.weekday()] * (1 + (weeks * 7 - back) / 600) + rnd.randint(-2, 2)))
        for _ in range(n):
            pieces = {rnd.choice(["ثوب", "قميص", "بنطلون", "شماغ", "بشت", "لحاف", "فستان"]):
                      rnd.randint(1, 4) for _ in range(rnd.randint(1, 2))}
            when = datetime.combine(day, datetime.min.time()) + timedelta(hours=rnd.randint(8, 21))
            oid, _ = create_order(conn, rnd.choice(ids), pieces, created_at=when)
            if back > 3:  # old orders are already finished
                conn.execute("UPDATE orders SET status='delivered' WHERE id=?", (oid,))
    conn.commit()


def main():
    DB_PATH.unlink(missing_ok=True)
    conn = connect()
    init_db(conn)

    print("== 1) إنشاء طلب جديد ==")
    cid = add_customer(conn, "أحمد", "0555555555")
    oid, codes = create_order(conn, cid, {"ثوب": 2, "شماغ": 1, "بشت": 1})
    print(f"طلب #{oid}، رموز QR:", codes)
    print("مسح أول رمز:", dict(scan_qr(conn, codes[0])))

    print("\n== 2) تتبع الطلب وإشعارات العميل ==")
    for _ in range(3):
        print("الحالة الجديدة:", advance_order(conn, oid))
    for n in conn.execute("SELECT message FROM notifications WHERE order_id=?", (oid,)):
        print(" -", n["message"])

    print("\n== 3) روبوت المحادثة ==")
    for q in ["وين طلبي؟", "بكم الثوب؟", "متى دوامكم؟"]:
        print(f"العميل: {q}\nالروبوت: {chatbot(conn, cid, q)}")

    print("\n== 4) بيانات تجريبية + التنبؤ ==")
    seed_demo(conn)
    mae_model, mae_naive = backtest(conn)
    print(f"متوسط الخطأ (طلب/يوم): نموذجنا {mae_model:.2f} مقابل الطريقة البسيطة {mae_naive:.2f}")
    preds = forecast(conn, date.today(), days=7)
    for row in staffing_plan(preds):
        flag = "  <- ذروة" if row["peak"] else ""
        print(f"{row['name']:<8} {row['day']}  طلبات متوقعة: {row['orders']:>2}  موظفين: {row['workers']}{flag}")

    print("\n== 5) تقارير SQL ==")
    for name in ("top_services", "top_customers", "low_inventory"):
        print(f"[{name}]")
        for r in run_report(conn, name):
            print("  ", dict(r))
    conn.close()
def generate_qr(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8"

if __name__ == "__main__":
    main()
