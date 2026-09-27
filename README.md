# 记账应用 (Expense Tracker)

一个用 Flask 写的个人记账 Web 应用。纯服务端渲染，无前端框架、无 CDN 依赖，图表全部由 Python 生成内联 SVG。

## 功能

- 记录收入/支出：金额、分类、日期、备注
- 首页本月概览：收入 / 支出 / 结余
- 交易明细：按月份、类型、分类筛选，实时合计
- 编辑 / 删除记录（删除前确认）
- 统计页：
  - 支出 / 收入分类条形图
  - 分类占比环形图（含金额与百分比）
  - 近 6 个月收支趋势折线图
- 服务端表单校验 + 友好错误提示

## 技术栈

| 层 | 技术 |
|---|---|
| Web 框架 | Flask |
| 数据库 | SQLite（标准库 `sqlite3`，零额外依赖） |
| 模板 | Jinja2 |
| 样式 | 原生 CSS |
| 图表 | 服务端渲染内联 SVG（无 JS 图表库） |

## 项目结构

```
expense-tracker/
├── app.py              # 应用入口 + 路由 + 校验逻辑
├── db.py               # 数据库连接、建表、预置分类
├── requirements.txt    # 依赖清单
├── static/
│   └── style.css       # 样式
└── templates/          # Jinja2 模板
    ├── base.html       # 母版（导航 + flash 消息）
    ├── index.html      # 首页概览
    ├── add.html        # 记一笔
    ├── list.html       # 交易明细 + 筛选
    ├── edit.html       # 编辑记录
    └── stats.html      # 统计图表
```

## 快速开始

需要 Python 3.x。

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行
python app.py

# 3. 浏览器打开
# http://127.0.0.1:5000
```

首次运行会自动创建 `expense.db` 并写入预置分类（工资、餐饮、交通等），无需手动建表。

## 说明

- `expense.db` 已加入 `.gitignore`，不会上传——每个人克隆后都会得到一份自己的空数据库。
- 图表使用**色盲安全**的标准配色，且金额/百分比都有文字标签，不只靠颜色传达信息。
