import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone

from flask import Flask, Response, g, jsonify, request, stream_with_context
from werkzeug.exceptions import HTTPException

app = Flask(__name__)
app.json.ensure_ascii = False   # 中文原样输出，不变成 \uXXXX
app.json.sort_keys = False      # 保持 code / data / msg 的书写顺序

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")


def load_dotenv(path):
    """读同目录下的 .env（KEY=VALUE 一行一条），已存在的环境变量优先。"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# 任务条目的可选扩展字段：前端清单页用得到，但都不是必填。
TEXT_FIELDS = {"summary": 200, "tag": 20, "priority": 20, "note": 2000}
ALLOWED_TAGS = {"学习", "项目", "生活", "复盘"}
ALLOWED_PRIORITIES = {"high", "medium", "low"}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# ---------------- 对话页配置：Key 只从服务器环境变量读，前端拿不到 ----------------
DEEPSEEK_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
CHAT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
MAX_CONTEXT_CHARS = 6000   # 上下文总长度上限，超了从最早的消息开始丢
SYSTEM_PROMPT = (
    "你是「今日待办」页面里的助手，帮用户把今天要做的事理清楚。"
    "只讨论任务整理、优先级、时间安排这类话题；和待办无关的问题，简短说明你帮不上。"
    "回答用简体中文，口语化，不超过 200 字；需要列步骤时最多 5 条。"
    "不知道的信息不要编，直接说不确定。"
)


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
@app.route("/api/chat", methods=["OPTIONS"])
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


# ---------------- 对话接口：流式转发，Key 只留在服务端 ----------------
def sse_error(msg):
    return "event: error\ndata: " + json.dumps({"msg": msg}, ensure_ascii=False) + "\n\n"


def read_chat_messages(payload):
    if not isinstance(payload, dict):
        return None, "请求体必须是 JSON 对象"
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return None, "messages 必须是非空数组"
    if len(messages) > 20:
        return None, "最多允许 20 条消息"
    cleaned = []
    for item in messages:
        if not isinstance(item, dict):
            return None, "messages 里的每一项都必须是对象"
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant"):
            return None, "role 只能是 user 或 assistant"
        if not isinstance(content, str) or not content.strip():
            return None, "content 必须是非空字符串"
        if len(content) > 4000:
            return None, "单条消息不能超过 4000 个字符"
        cleaned.append({"role": role, "content": content.strip()})
    if cleaned[-1]["role"] != "user":
        return None, "最后一条消息必须是 user"
    return cleaned, None


def trim_messages(messages):
    """上下文超长就从最早的一条开始丢，至少保留最后一轮。"""
    total = sum(len(m["content"]) for m in messages)
    while total > MAX_CONTEXT_CHARS and len(messages) > 2:
        removed = messages.pop(0)
        total -= len(removed["content"])
    return messages


def upstream_error_message(status):
    if status == 401:
        return "API Key 无效或已过期，请检查服务器环境变量 DEEPSEEK_API_KEY"
    if status == 402:
        return "账户余额不足，请到开放平台充值后再试"
    if status == 403:
        return "没有访问该模型的权限"
    if status == 429:
        return "请求太频繁，被限流了，等几秒再试"
    if status >= 500:
        return "模型服务暂时不可用，稍后再试"
    return "模型调用失败（HTTP " + str(status) + "）"


def stream_chat(messages):
    payload = {
        "model": CHAT_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "stream": True,
        "temperature": 0.7,
    }
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ.get("DEEPSEEK_API_KEY", "").strip(),
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        app.logger.warning("模型接口返回 %s: %s", exc.code, detail[:300])
        yield sse_error(upstream_error_message(exc.code))
        return
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            yield sse_error("模型响应超时，请重试")
        else:
            yield sse_error("连不上模型服务（" + str(exc.reason) + "），检查网络或 Base URL")
        return
    except TimeoutError:
        yield sse_error("模型响应超时，请重试")
        return
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("模型调用异常")
        yield sse_error("调用模型时出错：" + str(exc))
        return

    try:
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {}).get("content") or ""
                except (ValueError, KeyError, IndexError):
                    continue
                if delta:
                    yield "data: " + json.dumps({"delta": delta}, ensure_ascii=False) + "\n\n"
    except Exception:  # noqa: BLE001
        app.logger.exception("流式读取中断")
        yield sse_error("模型响应中断或超时，请重试")
        return

    yield "data: [DONE]\n\n"


@app.post("/api/chat")
def chat():
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        return fail("服务端未配置 DEEPSEEK_API_KEY", 500, code=500)
    messages, err = read_chat_messages(request.get_json(silent=True))
    if err:
        return fail(err)
    messages = trim_messages(messages)
    response = Response(stream_with_context(stream_chat(messages)), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


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
