import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "expense.db"

#建表语句
SCHEMA= """ 
CREATE TABLE IF NOT EXISTS CATEGORIES (
    id integer PRIMARY KEY AUTOINCREMENT,
    name text NOT NULL UNIQUE,
    type text not null check(type in ('income', 'expense'))
);

create table if not exists transactions (
    id integer primary key autoincrement,
    type text not null check(type in ('income', 'expense')),
    amount real not null,
    category_id integer not null references categories(id),
    date text not null,
    note text,
    created_at text default (datetime('now','localtime'))
);
"""
#预置分类
default_categories = [
    ("工资","income"),
    ("奖金","income"),
    ("理财","income"),
    ("餐饮","expense"),
    ("交通","expense"),
    ("购物","expense"),
    ("居住","expense"),
    ("娱乐","expense"),
    ("其他","expense")
]

def get_db():
    """返回一个数据库连接"""
    conn=sqlite3.connect(DB_PATH)
    conn.row_factory=sqlite3.Row
    return conn

def init_db():
    """建表+写入预置分类，应用启动时调用一次"""
    with get_db() as conn:
        conn.executescript(SCHEMA)
        for name, type in default_categories:
            conn.execute(
                "insert or ignore into categories (name, type) values (?, ?)",
                (name, type),
            )
