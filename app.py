import json
import os
import re
import sqlite3
from datetime import datetime, timezone

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

app = Flask(__name__)
app.json.ensure_ascii = False   # 中文原样输出，不变成 \uXXXX
app.json.sort_keys = False      # 保持 code / data / msg 的书写顺序

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")

# 任务条目的可选扩展字段：前端清单页用得到，但都不是必填。
TEXT_FIELDS = {"summary": 200, "tag": 20, "priority": 20, "note": 2000}
ALLOWED_TAGS = {"学习", "项目", "生活", "复盘"}
ALLOWED_PRIORITIES = {"high", "medium", "low"}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------------- 数据库 ----------------
def get_db():
    """每个请求一个连接，挂在 g 上，请求结束自动关闭。"""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL,
                done       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    NOT NULL,
                extra      TEXT    NOT NULL DEFAULT '{}'
            )
            """
        )
        # 旧库补列：早期版本没有 extra 字段。
        columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
        if "extra" not in columns:
            conn.execute("ALTER TABLE items ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'")


def row_to_dict(row):
    item = {
        "id": row["id"],
        "title": row["title"],
        "done": bool(row["done"]),
        "created_at": row["created_at"],
    }
    try:
        extra = json.loads(row["extra"] or "{}")
    except (TypeError, ValueError):
        extra = {}
    if isinstance(extra, dict):
        item.update(extra)
    return item


# ---------------- 统一返回 ----------------
def ok(data=None, msg="ok"):
    return jsonify(code=0, data=data, msg=msg)


def fail(msg, status=400, code=None):
    return jsonify(code=code or status, data=None, msg=msg), status


# ---------------- 参数校验 ----------------
def read_title(payload):
    """title 必填：字符串、去空格后非空、长度 <= 50。"""
    if "title" not in payload:
        return None, "缺少字段 title"
    value = payload["title"]
    if not isinstance(value, str):
        return None, "title 必须是字符串"
    value = value.strip()
    if not value:
        return None, "title 不能为空"
    if len(value) > 50:
        return None, "title 长度不能超过 50 个字符"
    return value, None


def read_done(payload, default=False):
    if "done" not in payload:
        return default, None
    value = payload["done"]
    if not isinstance(value, bool):
        return None, "done 必须是布尔值 true/false"
    return value, None


def read_extra(payload):
    """读取可选扩展字段，只收白名单里的键，类型不对返回 400 的原因。"""
    extra = {}

    for key, limit in TEXT_FIELDS.items():
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, str):
            return None, key + " 必须是字符串"
        value = value.strip()
        if len(value) > limit:
            return None, key + " 长度不能超过 " + str(limit) + " 个字符"
        if key == "tag" and value and value not in ALLOWED_TAGS:
            return None, "tag 只能是 学习 / 项目 / 生活 / 复盘"
        if key == "priority" and value and value not in ALLOWED_PRIORITIES:
            return None, "priority 只能是 high / medium / low"
        extra[key] = value

    if "estimateMinutes" in payload:
        value = payload["estimateMinutes"]
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "estimateMinutes 必须是整数"
        if value < 0 or value > 600:
            return None, "estimateMinutes 必须在 0 到 600 之间"
        extra["estimateMinutes"] = value

    if "steps" in payload:
        value = payload["steps"]
        if not isinstance(value, list):
            return None, "steps 必须是数组"
        if len(value) > 50:
            return None, "steps 最多 50 条"
        steps = []
        for step in value:
            if not isinstance(step, str):
                return None, "steps 里的每一项都必须是字符串"
            step = step.strip()
            if len(step) > 200:
                return None, "steps 单条长度不能超过 200 个字符"
            if step:
                steps.append(step)
        extra["steps"] = steps

    if "dueDate" in payload:
        value = payload["dueDate"]
        if not isinstance(value, str) or not DATE_PATTERN.match(value):
            return None, "dueDate 必须是 YYYY-MM-DD 格式"
        extra["dueDate"] = value

    if "dueTime" in payload:
        value = payload["dueTime"]
        if not isinstance(value, str) or not TIME_PATTERN.match(value):
            return None, "dueTime 必须是 HH:MM 格式"
        extra["dueTime"] = value

    return extra, None


# ---------------- 跨域：前端页面和接口不同源，必须由服务端放行 ----------------
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    response.headers["Access-Control-Allow-Origin"] = origin or "*"
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


@app.route("/api/items", methods=["OPTIONS"])
@app.route("/api/items/<int:item_id>", methods=["OPTIONS"])
def cors_preflight(item_id=None):
    # 浏览器发预检时，这里只回 200 和响应头，after_request 会补全 CORS。
    return ("", 204)


# ---------------- 接口 ----------------
@app.get("/api/items")
def list_items():
    rows = get_db().execute("SELECT * FROM items ORDER BY id DESC").fetchall()
    return ok([row_to_dict(r) for r in rows])


@app.post("/api/items")
def create_item():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return fail("请求体必须是 JSON 对象，且 Content-Type 为 application/json")

    title, err = read_title(payload)
    if err:
        return fail(err)
    done, err = read_done(payload)
    if err:
        return fail(err)
    extra, err = read_extra(payload)
    if err:
        return fail(err)

    created_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    db = get_db()
    cur = db.execute(
        "INSERT INTO items (title, done, created_at, extra) VALUES (?, ?, ?, ?)",
        (title, int(done), created_at, json.dumps(extra, ensure_ascii=False)),
    )
    db.commit()
    row = db.execute("SELECT * FROM items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return ok(row_to_dict(row), "创建成功"), 201


@app.put("/api/items/<int:item_id>")
def update_item(item_id):
    db = get_db()
    row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return fail("记录不存在", 404)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not payload:
        return fail("请求体必须是非空 JSON 对象")

    title, done = row["title"], bool(row["done"])
    if "title" in payload:
        title, err = read_title(payload)
        if err:
            return fail(err)
    if "done" in payload:
        done, err = read_done(payload)
        if err:
            return fail(err)

    extra, err = read_extra(payload)
    if err:
        return fail(err)
    merged_extra = json.loads(row["extra"] or "{}")
    if not isinstance(merged_extra, dict):
        merged_extra = {}
    merged_extra.update(extra)

    db.execute(
        "UPDATE items SET title = ?, done = ?, extra = ? WHERE id = ?",
        (title, int(done), json.dumps(merged_extra, ensure_ascii=False), item_id),
    )
    db.commit()
    row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return ok(row_to_dict(row), "修改成功")


@app.delete("/api/items/<int:item_id>")
def delete_item(item_id):
    db = get_db()
    row = db.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return fail("记录不存在", 404)
    db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    db.commit()
    return ok({"id": item_id}, "删除成功")


# ---------------- 全局错误处理：一律 JSON，不吐 HTML ----------------
@app.errorhandler(404)
def not_found(e):
    return fail("接口不存在", 404)


@app.errorhandler(405)
def method_not_allowed(e):
    return fail("请求方法不允许", 405)


@app.errorhandler(HTTPException)
def handle_http_error(e):
    return fail(e.description or e.name, e.code or 500)


@app.errorhandler(Exception)
def handle_unexpected(e):
    app.logger.exception("未捕获异常")
    return fail("服务器内部错误", 500)


init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
