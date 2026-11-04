from flask import Flask, render_template, request, redirect, url_for,flash  
from datetime import datetime,timedelta
import db
import math
import calendar
import statistics
import os
import sys
from pathlib import Path

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

if "--demo" in sys.argv or os.environ.get("EXPENSE_DEMO") == "1":
    db.DB_PATH = Path(__file__).parent / "demo.db"

db.init_db()


def get_categories(conn):
    """返回所有分类 """
    income=conn.execute(
        "SELECT * FROM categories WHERE type='income' ORDER BY id").fetchall()
    expense=conn.execute(
        "SELECT * FROM categories WHERE type='expense' ORDER BY id").fetchall()
    return income,expense

def validate_transaction(form, conn):
    """校验记一笔/编辑表单。返回 (errors, data)；errors 为空表示通过。"""
    errors = []
    typ = form.get("type", "")
    amount_str = form.get("amount", "")
    date = form.get("date", "")
    category_id_str = form.get("category_id", "")
    note = form.get("note", "")

    if typ not in ("income", "expense"):
        errors.append("请选择收入或支出")

    try:
        amount = float(amount_str)
        if amount <= 0:
            errors.append("金额必须大于 0")
    except (ValueError, TypeError):
        amount = None
        errors.append("金额必须是有效的数字")

    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (ValueError, TypeError):
        errors.append("请选择有效的日期")

    category_id = None
    try:
        category_id = int(category_id_str)
    except (ValueError, TypeError):
        errors.append("请选择有效的分类")

    if category_id is not None:
        cat = conn.execute("SELECT type FROM categories WHERE id=?", (category_id,)).fetchone()
        if cat is None:
            errors.append("分类不存在")
        elif cat["type"] != typ:
            errors.append("分类与类型不匹配")

    data = {"type": typ, "amount": amount, "category_id": category_id,
            "date": date, "note": note}
    return errors, data
def last_complete_month():
    """返回最近一个已结束的月份，例如 2026-11-04 -> '2026-10'"""
    first_of_this_month = datetime.now().replace(day=1)
    return (first_of_this_month - timedelta(days=1)).strftime("%Y-%m")


def month_bounds(month):
    """返回该月的 [开始, 下月开始) 两个日期字符串"""
    y, m = int(month[:4]), int(month[5:7])
    start = f"{y:04d}-{m:02d}-01"
    if m == 12:
        end = f"{y + 1:04d}-01-01"
    else:
        end = f"{y:04d}-{m + 1:02d}-01"
    return start, end


def month_range(n, end_month=None):
    """返回截至 end_month（含）的最近 n 个月，从旧到新"""
    if end_month:
        y, m = int(end_month[:4]), int(end_month[5:7])
    else:
        now = datetime.now()
        y, m = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    out.reverse()
    return out


def pct_change(current, previous):
    """环比变化百分比；上期为 0 时返回 None"""
    if not previous:
        return None
    return (current - previous) / previous * 100


def build_month_analysis(conn, month):
    """计算某个月的收入、支出、环比、储蓄率、异常支出等指标"""
    y, m = int(month[:4]), int(month[5:7])
    days = calendar.monthrange(y, m)[1]
    prev_month = month_range(2, month)[0]

    # CTE + LAG：先把上月和本月拼成两行，再用窗口函数取上一行
    sql = """
    WITH months(month) AS (VALUES (?), (?)),
    monthly AS (
        SELECT m.month,
               COALESCE(SUM(CASE WHEN t.type = 'income'  THEN t.amount END), 0) AS income,
               COALESCE(SUM(CASE WHEN t.type = 'expense' THEN t.amount END), 0) AS expense
        FROM months m
        LEFT JOIN transactions t ON substr(t.date, 1, 7) = m.month
        GROUP BY m.month
    ),
    with_prev AS (
        SELECT month, income, expense,
               LAG(income)  OVER (ORDER BY month) AS prev_income,
               LAG(expense) OVER (ORDER BY month) AS prev_expense
        FROM monthly
    )
    SELECT * FROM with_prev WHERE month = ?
    """
    cur = conn.execute(sql, (prev_month, month, month)).fetchone()

    income = cur["income"]
    expense = cur["expense"]
    balance = income - expense
    savings_rate = balance / income * 100 if income else None
    daily_avg = expense / days

    # 最大支出分类
    top = conn.execute("""
        SELECT c.name, SUM(t.amount) AS total
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE t.type = 'expense' AND t.date LIKE ?
        GROUP BY c.name
        ORDER BY total DESC
        LIMIT 1
    """, (month + "%",)).fetchone()
    top_share = top["total"] / expense * 100 if top and expense else 0

    # 异常检测：剔除居住（房租固定），按均值 + 2σ 找异常
    expense_rows = conn.execute("""
        SELECT t.amount, t.date, t.note, c.name AS category
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE t.type = 'expense' AND t.date LIKE ? AND c.name <> '居住'
    """, (month + "%",)).fetchall()
    amounts = [r["amount"] for r in expense_rows]
    if len(amounts) >= 3:
        mean = statistics.mean(amounts)
        std = statistics.pstdev(amounts)
        threshold = mean + 2 * std
        anomalies = sorted(
            [r for r in expense_rows if r["amount"] > threshold],
            key=lambda r: r["amount"], reverse=True,
        )
    else:
        mean = std = threshold = 0
        anomalies = []

    # 最大可变支出分类（剔除房租）
    variable_top = conn.execute("""
        SELECT c.name, SUM(t.amount) AS total
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE t.type = 'expense' AND t.date LIKE ? AND c.name <> '居住'
        GROUP BY c.name
        ORDER BY total DESC
        LIMIT 1
    """, (month + "%",)).fetchone()
    variable_total = sum(amounts)

    # 自动生成中文结论
    insights = []
    income_change = pct_change(income, cur["prev_income"])
    expense_change = pct_change(expense, cur["prev_expense"])
    balance_change = pct_change(balance, cur["prev_income"] - cur["prev_expense"])

    if income_change is None:
        insights.append(f"本月收入 ¥{income:,.2f}，支出 ¥{expense:,.2f}。")
    else:
        insights.append(
            f"本月收入 ¥{income:,.2f}（环比 {income_change:+.1f}%），"
            f"支出 ¥{expense:,.2f}（环比 {expense_change:+.1f}%）。"
        )

    if top:
        insights.append(
            f"{top['name']}支出 ¥{top['total']:,.2f}，"
            f"占总支出的 {top_share:.1f}%，是最大支出项。"
        )

    if variable_top:
        var_share = variable_top["total"] / variable_total * 100 if variable_total else 0
        insights.append(
            f"剔除房租后，{variable_top['name']} ¥{variable_top['total']:,.2f} "
            f"是最大的可变支出，占可变支出的 {var_share:.1f}%。"
        )

    if anomalies:
        first = anomalies[0]
        label = first["note"] or first["category"]
        insights.append(
            f"按「均值 + 2σ」识别出 {len(anomalies)} 笔异常支出，"
            f"最大一笔 ¥{first['amount']:,.2f}（{label}）。"
        )
    else:
        insights.append("本月没有识别到明显的异常支出。")

    return {
        "month": month,
        "income": income,
        "expense": expense,
        "balance": balance,
        "income_change": income_change,
        "expense_change": expense_change,
        "balance_change": balance_change,
        "savings_rate": savings_rate,
        "daily_avg": daily_avg,
        "days": days,
        "top": top,
        "top_share": top_share,
        "anomaly_count": len(anomalies),
        "anomaly_max": dict(anomalies[0]) if anomalies else None,
        "anomaly_threshold": threshold,
        "insights": insights,
    }

@app.route("/")
def index():
    conn = db.get_db()
    this_month = datetime.now().strftime("%Y-%m")   # 例如 '2026-09'

    # 本月收入、支出合计（没有记录时 SUM 是 NULL，用 or 0 兜底）
    row = conn.execute("""
        SELECT
            SUM(CASE WHEN type='income'  THEN amount ELSE 0 END) AS income,
            SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expense
        FROM transactions
        WHERE date LIKE ?
    """, (this_month + "%",)).fetchone()

    # 最近 10 条记录，JOIN 分类表拿到分类名
    recent = conn.execute("""
        SELECT t.*, c.name AS category
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        ORDER BY t.date DESC, t.id DESC
        LIMIT 10
    """).fetchall()
    conn.close()

    return render_template(
        "index.html",
        income=row["income"] or 0,
        expense=row["expense"] or 0,
        recent=recent,
        this_month=this_month,
    )

@app.route("/add", methods=["GET", "POST"])
def add():
    conn = db.get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    if request.method == "POST":
        errors, data = validate_transaction(request.form, conn)
        if errors:
            income_cats, expense_cats = get_categories(conn)
            conn.close()
            for e in errors:
                flash(e, "error")
            return render_template("add.html",
                income_cats=income_cats, expense_cats=expense_cats,
                form=dict(request.form)), 400

        conn.execute(
            "INSERT INTO transactions(type, amount, category_id, date, note) VALUES (?,?,?,?,?)",
            (data["type"], data["amount"], data["category_id"], data["date"], data["note"]),
        )
        conn.commit()
        conn.close()
        flash("已保存", "success")
        return redirect(url_for("index"))

    # GET：显示空表单
    income_cats, expense_cats = get_categories(conn)
    conn.close()
    form = {"type": "expense", "category_id": "", "amount": "", "date": today, "note": ""}
    return render_template("add.html", income_cats=income_cats, expense_cats=expense_cats, form=form)


@app.route("/transactions")
def transactions():
    conn = db.get_db()

    # 从 URL 查询串读取筛选条件（GET 请求用 request.args）
    month = request.args.get("month", "")             # '2026-09' 或 ''
    typ = request.args.get("type", "")                # 'income'/'expense'/'' 表示全部
    category_id = request.args.get("category_id", "") # '' 表示全部

    # 根据有没有填条件，动态拼接 WHERE
    where = []
    params = []
    if month:
        where.append("t.date LIKE ?")
        params.append(month + "%")
    if typ:
        where.append("t.type = ?")
        params.append(typ)
    if category_id:
        where.append("t.category_id = ?")
        params.append(category_id)

    sql = "SELECT t.*, c.name AS category FROM transactions t JOIN categories c ON c.id = t.category_id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.date DESC, t.id DESC"

    rows = conn.execute(sql, params).fetchall()

    # 筛选结果的收支合计
    total_income = sum(r["amount"] for r in rows if r["type"] == "income")
    total_expense = sum(r["amount"] for r in rows if r["type"] == "expense")

    cats = conn.execute("SELECT * FROM categories ORDER BY type, id").fetchall()
    conn.close()

    return render_template("list.html",
        rows=rows, cats=cats,
        month=month, typ=typ, category_id=category_id,
        total_income=total_income, total_expense=total_expense)


@app.route("/edit/<int:tx_id>", methods=["GET", "POST"])
def edit(tx_id):
    conn = db.get_db()

    if request.method == "POST":
        errors, data = validate_transaction(request.form, conn)
        if errors:
            income_cats, expense_cats = get_categories(conn)
            conn.close()
            for e in errors:
                flash(e, "error")
            return render_template("edit.html",
                income_cats=income_cats, expense_cats=expense_cats,
                form=dict(request.form)), 400

        conn.execute(
            "UPDATE transactions SET type=?, amount=?, category_id=?, date=?, note=? WHERE id=?",
            (data["type"], data["amount"], data["category_id"], data["date"], data["note"], tx_id),
        )
        conn.commit()
        conn.close()
        flash("已修改", "success")
        return redirect(url_for("transactions"))

    # GET：查出原记录，填进表单
    t = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    income_cats, expense_cats = get_categories(conn)
    conn.close()

    if t is None:
        return "记录不存在", 404
    form = {"type": t["type"], "category_id": str(t["category_id"]),
            "amount": str(t["amount"]), "date": t["date"], "note": t["note"] or ""}
    return render_template("edit.html", income_cats=income_cats, expense_cats=expense_cats, form=form)



@app.route("/delete/<int:tx_id>", methods=["POST"])
def delete(tx_id):
    conn = db.get_db()
    conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    conn.commit()
    conn.close()
    flash("已删除", "success")
    return redirect(url_for("transactions"))

@app.route("/stats")
def stats():
    conn = db.get_db()
    # 统计最近一个完整月份：月初当月数据不完整，直接做环比会失真
    this_month = last_complete_month()

    # 支出、收入各自的分类图表（条形图 + 环形图）
    expense_bars, expense_slices, expense_total = build_category_chart(conn, "expense", this_month)
    income_bars, income_slices, income_total = build_category_chart(conn, "income", this_month)

    # ===== 折线图：近 6 个完整月收支 =====
    months = month_range(6, this_month)
    start = month_bounds(months[0])[0]
    end = month_bounds(this_month)[1]
    rows = conn.execute("""
        SELECT substr(date, 1, 7) AS m, type, SUM(amount) AS total
        FROM transactions
        WHERE date >= ? AND date < ?
        GROUP BY m, type
    """, (start, end)).fetchall()

    # ===== 月度分析指标 =====
    analysis = build_month_analysis(conn, this_month)
    conn.close()

    by_month = {(r["m"], r["type"]): r["total"] for r in rows}
    income = [by_month.get((m, "income"), 0) for m in months]
    expense = [by_month.get((m, "expense"), 0) for m in months]

    # ===== 坐标换算 =====
    ML, MR, MT, MB = 48, 56, 24, 36
    left, right = ML, 640 - MR
    top, bottom = MT, 320 - MB
    top_val = nice_ceil(max(max(income, default=0), max(expense, default=0)))

    step = (right - left) / (len(months) - 1)
    xpos = [left + i * step for i in range(len(months))]

    def y_of(v):
        return bottom - (v / top_val) * (bottom - top)

    income_series = [{"m": m, "x": x, "y": y_of(v), "v": v}
                     for m, x, v in zip(months, xpos, income)]
    expense_series = [{"m": m, "x": x, "y": y_of(v), "v": v}
                      for m, x, v in zip(months, xpos, expense)]

    income_line = " ".join(f"{p['x']:.1f},{p['y']:.1f}" for p in income_series)
    expense_line = " ".join(f"{p['x']:.1f},{p['y']:.1f}" for p in expense_series)

    month_labels = [{"label": f"{int(m[5:7])}月", "x": x}
                    for m, x in zip(months, xpos)]
    ticks = [{"label": f"{t:,.0f}", "y": y_of(t)}
             for t in [0, top_val/4, top_val/2, 3*top_val/4, top_val]]

    return render_template("stats.html",
        expense_bars=expense_bars, expense_slices=expense_slices, expense_total=expense_total,
        income_bars=income_bars, income_slices=income_slices, income_total=income_total,
        this_month=this_month,
        income_line=income_line, expense_line=expense_line,
        income_series=income_series, expense_series=expense_series,
        month_labels=month_labels, ticks=ticks,
        left=left, right=right, bottom=bottom,
        analysis=analysis)




def nice_ceil(v):
    """把最大值向上取整到一个'好看'的数（100/200/500/1000…），用于 y 轴上限"""
    if v <= 0:
        return 100
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 5, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp



# 环形图配色：色盲安全的标准配色，按顺序取
DONUT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
DONUT_R = 52                     # 圆环半径
DONUT_C = 2 * math.pi * DONUT_R  # 圆周长，用于按比例切扇区


def build_category_chart(conn, typ, month):
    """查某类型(收入/支出)本月的分类合计，并算好条形图和环形图的数据"""
    rows = conn.execute("""
        SELECT c.name AS name, SUM(t.amount) AS total
        FROM transactions t JOIN categories c ON c.id = t.category_id
        WHERE t.type = ? AND t.date LIKE ?
        GROUP BY c.name
        ORDER BY total DESC
    """, (typ, month + "%")).fetchall()

    grand = sum(r["total"] for r in rows)
    max_total = max((r["total"] for r in rows), default=0)

    bars, slices, cum = [], [], 0.0
    for i, r in enumerate(rows):
        total = r["total"]
        bars.append({
            "name": r["name"], "total": total,
            "width": round(360 * total / max_total) if max_total else 0,
        })
        frac = total / grand if grand else 0
        arc = frac * DONUT_C
        visible = max(arc - 2, 0)   # 每个扇区之间留 2px 缝隙
        slices.append({
            "name": r["name"], "total": total,
            "percent": round(frac * 100, 1),
            "color": DONUT_COLORS[i % len(DONUT_COLORS)],
            "dasharray": f"{visible:.2f} {DONUT_C:.2f}",
            "dashoffset": f"{-cum:.2f}",
        })
        cum += arc

    return bars, slices, grand


if __name__ == "__main__":
    app.run(debug=True)
