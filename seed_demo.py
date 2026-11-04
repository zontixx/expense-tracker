#生成演示数据
import calendar
import random
from datetime import date,timedelta
from pathlib import Path

import db

DB_PATH = Path(__file__).parent / "demo.db"
db.DB_PATH = DB_PATH
db.init_db()

random.seed(42)
TODAY = date.today()

def add_months(d, months):
    """在 d 的基础上加 months 个月；目标月份没有这一天时取月末"""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)

START = add_months(TODAY.replace(day=1), -11)

conn = db.get_db()
cats = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}
conn.execute("DELETE FROM transactions")

rows = []

def add(d, typ, cat, amount, note):
    rows.append((typ, round(amount, 2), cats[cat], d.isoformat(), note))

# 1) 每天 0-4 笔日常支出，周末概率和金额更高
d = START
while d <= TODAY:
    weekend = d.weekday() >= 5
    n = random.choices([0, 1, 2, 3, 4], weights=[2, 3, 4, 3, 1])[0]
    if weekend:
        n += random.choice([0, 1, 1])
    for _ in range(n):
        cat = random.choices(
            ["餐饮", "交通", "购物", "娱乐", "其他"],
            weights=[45, 22, 15, 12, 6],
        )[0]
        if cat == "餐饮":
            amount = random.uniform(60, 220) if weekend else random.uniform(15, 80)
            note = random.choice(["午餐", "晚餐", "外卖", "咖啡", "和朋友吃饭"])
        elif cat == "交通":
            amount = random.uniform(3, 60)
            note = random.choice(["地铁", "公交", "打车", "共享单车"])
        elif cat == "购物":
            amount = random.uniform(50, 500) if weekend else random.uniform(20, 250)
            note = random.choice(["超市采购", "日用品", "网购", "衣服"])
        elif cat == "娱乐":
            amount = random.uniform(30, 250)
            note = random.choice(["电影", "健身", "展览", "游戏"])
        else:
            amount = random.uniform(20, 180)
            note = random.choice(["药品", "话费", "理发", "其他"])
        add(d, "expense", cat, amount, note)
    d += timedelta(days=1)

# 2) 每月 1 号房租
d = START
while d <= TODAY:
    add(d, "expense", "居住", 2200, "房租")
    d = add_months(d, 1)

# 3) 每月 1 号工资（月初发薪，保证当月一开始就有收入）
d = START.replace(day=1)
while d <= TODAY:
    add(d, "income", "工资", random.uniform(9000, 9800), "工资")
    d = add_months(d, 1)

# 4) 季度奖金：3/6/9/12 月 15 号
d = START.replace(day=15)
while d <= TODAY:
    if d.month in (3, 6, 9, 12):
        add(d, "income", "奖金", random.uniform(2500, 5000), "季度奖金")
    d = add_months(d, 1)

# 5) 偶尔的理财收益
d = START.replace(day=20)
while d <= TODAY:
    if random.random() < 0.35:
        add(d, "income", "理财", random.uniform(50, 300), "理财收益")
    d = add_months(d, 1)

# 6) 两笔大额异常支出，用来演示异常检测
for months_ago, amount, note in [(9, 3800, "换电脑"), (4, 2600, "家电维修")]:
    dd = add_months(TODAY, -months_ago)
    if START <= dd <= TODAY:
        add(dd, "expense", "购物", amount, note)

rows.sort(key=lambda r: (r[3], r[0]))
conn.executemany(
    "INSERT INTO transactions(type, amount, category_id, date, note) VALUES (?,?,?,?,?)",
    rows,
)
conn.commit()
conn.close()

income = sum(r[1] for r in rows if r[0] == "income")
expense = sum(r[1] for r in rows if r[0] == "expense")
print(f"演示数据库已生成：{DB_PATH}")
print(f"记录数：{len(rows)}    时间范围：{START} ~ {TODAY}")
print(f"收入合计：{income:,.2f} 元    支出合计：{expense:,.2f} 元")
print("启动演示：python app.py --demo")