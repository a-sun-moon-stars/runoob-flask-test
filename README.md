# runoob-flask-test

Flask + SQLite 的任务条目接口，提供列表、新增、修改、删除四个接口，数据存在本地数据库文件里，重启服务不丢。配套前端是 [wangye](https://github.com/a-sun-moon-stars/wangye) 的今日待办页面。

- 仓库：https://github.com/a-sun-moon-stars/runoob-flask-test
- 线上接口：https://sunmoonstars.pythonanywhere.com/api/items

## 技术栈

Python 3.10+、Flask 3.1、SQLite（标准库 `sqlite3`，无需额外安装）。

## 安装与启动

首次准备环境：

```powershell
cd C:\Users\zhc\runoob-flask-test
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

启动：

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

服务监听 `http://127.0.0.1:5000`，首次启动自动创建 `app.db` 和 `items` 表，按 `Ctrl+C` 停止。端口被占用时先 `netstat -ano | findstr :5000` 查 PID，再 `taskkill /F /PID <PID>`。

## 对话页配置（任务四）

复制 `.env.example` 为 `.env`，填自己的 Key：

```text
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_MODEL=deepseek-chat
```

`app.py` 启动时读同目录的 `.env`，已存在的环境变量优先；`.env` 已写进 `.gitignore`，不会进仓库。服务器（PythonAnywhere）上同样把 `.env` 放在 `app.py` 同目录即可，或在 WSGI 文件里设置 `os.environ["DEEPSEEK_API_KEY"]`。

```bash
curl -N -X POST http://127.0.0.1:5000/api/chat -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"今天先做哪件？"}]}'
```

## 接口约定

所有接口返回统一结构：

```json
{"code": 0, "data": ..., "msg": "ok"}
```

`code` 为 `0` 表示成功，失败时为对应的 HTTP 状态码；`data` 失败时为 `null`；`msg` 写明结果或失败原因。

### 接口列表

| 方法 | 路径 | 参数 | 返回示例 |
| --- | --- | --- | --- |
| GET | `/api/items` | 无 | `{"code":0,"data":[{"id":1,"title":"写接口文档","done":false,"created_at":"2026-11-12T16:51:46+08:00","tag":"项目"}],"msg":"ok"}` |
| POST | `/api/items` | body：`title` 必填；`done`、`summary`、`tag`、`priority`、`dueDate`、`dueTime`、`estimateMinutes`、`steps`、`note` 可选 | `201` `{"code":0,"data":{"id":1,"title":"写接口文档","done":false,"created_at":"..."},"msg":"创建成功"}` |
| PUT | `/api/items/<id>` | path：`id` 整数；body：任一可写字段，至少给一个 | `{"code":0,"data":{"id":1,"title":"写接口文档","done":true},"msg":"修改成功"}` |
| DELETE | `/api/items/<id>` | path：`id` 整数 | `{"code":0,"data":{"id":1},"msg":"删除成功"}` |

附加字段统一存进 `items.extra`（JSON 文本），GET 时展开合并到返回对象里。

### 对话接口（流式）

| 方法 | 路径 | 参数 | 返回 |
| --- | --- | --- | --- |
| POST | `/api/chat` | body：`messages` 数组，`role` 为 `user`/`assistant`，`content` 非空且 ≤ 4000 字符，最后一条必须是 `user`，最多 20 条 | `text/event-stream`：`data: {"delta":"..."}` 逐字返回，`data: [DONE]` 结束；失败时 `event: error` + `{"msg":"..."}` |

- Key 只从服务端环境变量 `DEEPSEEK_API_KEY` 读取，前端 JS 里没有 Key；系统提示词在服务端拼，不接受前端传入。
- 上下文超过 6000 字符时从最早的消息开始丢，至少保留最后一轮。
- `401` Key 无效、`402` 余额不足、`403` 无权限、`429` 限流、超时、连不上，都会通过 `event: error` 返回可读中文，服务不中断。

### 参数校验

- `title`：必填、字符串、去空格后非空、不超过 50 字符。
- `done`：可选，必须是布尔值。
- `summary` ≤ 200 字符；`tag` 只能是 `学习`、`项目`、`生活`、`复盘`；`priority` 只能是 `high`、`medium`、`low`；`note` ≤ 2000 字符。
- `estimateMinutes`：0 到 600 的整数；`steps`：字符串数组，最多 50 条、每条 ≤ 200 字符。
- `dueDate`：`YYYY-MM-DD`；`dueTime`：`HH:MM`。
- 请求体不是合法 JSON、缺字段或类型不对时返回 `400` 并说明原因，服务不会中断。

### 错误返回

| 状态码 | 场景 | 示例 |
| --- | --- | --- |
| 400 | 请求体缺失、字段缺失、类型错误 | `{"code":400,"data":null,"msg":"缺少字段 title"}` |
| 404 | 记录或接口路径不存在 | `{"code":404,"data":null,"msg":"记录不存在"}` |
| 405 | 请求方法不允许 | `{"code":405,"data":null,"msg":"请求方法不允许"}` |
| 500 | 未捕获的服务器异常 | `{"code":500,"data":null,"msg":"服务器内部错误"}` |

所有错误都以 JSON 返回，不把 HTML 报错页给客户端。

## 数据存储

```sql
CREATE TABLE items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    extra      TEXT    NOT NULL DEFAULT '{}'
);
```

旧库没有 `extra` 列时，启动会自动 `ALTER TABLE` 补上，已有数据不受影响。`DB_PATH` 按 `__file__` 定位，服务在哪个目录启动都写同一个 `app.db`。

## 跨域

页面和接口不同源，浏览器会先做 CORS 预检。`app.py` 用 `after_request` 回显 `Origin`，设置 `Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS`、`Access-Control-Allow-Headers: Content-Type`、`Access-Control-Max-Age: 86400`、`Vary: Origin`；`OPTIONS /api/items` 和 `OPTIONS /api/items/<id>` 返回 `204`。

```powershell
curl.exe -i -X OPTIONS http://127.0.0.1:5000/api/items -H "Origin: http://localhost:8000" -H "Access-Control-Request-Method: POST"
```

应返回 `204` 并带 `Access-Control-Allow-Origin: http://localhost:8000`。

## 部署到 PythonAnywhere

已部署实例：https://sunmoonstars.pythonanywhere.com ，WSGI 指向 `/home/Sunmoonstars/runoob-flask-test`。

1. Files 里建 `/home/USERNAME/runoob-flask-test`，上传 `app.py`；也可以在 Bash 里 `cat > ~/runoob-flask-test/app.py` 粘贴源码。
2. `pip3 install --user flask==3.1.3`（示例代码需要 Flask 2.2 以上）。
3. Web → Add a new web app → Manual configuration，项目路径填 `/home/USERNAME/runoob-flask-test`；WSGI 配置文件用仓库里的 `pythonanywhere_wsgi.py` 替换，改掉 `USERNAME`。
4. Reload，访问 `https://USERNAME.pythonanywhere.com/api/items` 应返回 `{"code":0,...}`。

说明：PythonAnywhere 用 WSGI 托管，不会执行 `app.run()`；免费实例有 CPU 秒数限制，演示够用；数据库是本地文件，迁移前记得备份 `app.db`。

### 部署踩坑记录

站点打开是 `Something went wrong :-(`，日志：

```text
ModuleNotFoundError: No module named 'app'
  File "/var/www/sunmoonstars_pythonanywhere_com_wsgi.py", line 7, in <module>
    from app import app as application
```

WSGI 路径是对的，但 `ls -la /home/USERNAME/runoob-flask-test/` 只有 `.` 和 `..`，`stat app.py` 报 `No such file or directory`——Files 里一次“看起来成功”的上传并没有真正落盘。

解决：在 Bash 里直接写 `app.py`（`cat >` 粘贴，或 gzip+base64 解码落盘），`ls -l` 确认有大小，`touch /var/www/USERNAME_pythonanywhere_com_wsgi.py` 触发重载，再 `curl` 接口，返回 `{"code":0,"data":[],"msg":"ok"}` 即为成功。

## 提交说明

仓库不包含虚拟环境和运行时数据库：`.venv/`、`__pycache__/`、`*.pyc`、`*.db`、`body.json`。
