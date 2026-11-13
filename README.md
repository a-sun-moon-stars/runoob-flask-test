# runoob-flask-test

一个用 Flask + SQLite 实现的任务条目接口服务，提供列表、新增、修改、删除四个接口，数据保存在本地数据库文件中，重启服务后不丢失。配套前端是 `wangye` 仓库里的今日待办页面。

## 技术栈

- Python 3.10+（本机 3.15）
- Flask 3.1
- SQLite（Python 标准库 `sqlite3`，无需额外安装）

## 目录结构

```
runoob-flask-test/
├── app.py            # 应用入口：路由、参数校验、错误处理、数据库初始化、CORS
├── requirements.txt  # Flask、gunicorn
├── render.yaml       # Render 部署描述（备选）
├── pythonanywhere_wsgi.py  # PythonAnywhere 的 WSGI 配置示例
├── app.db            # SQLite 数据库，首次启动自动创建
└── .venv/            # 虚拟环境，不提交到仓库
```

## 安装与启动

首次准备环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

启动服务：

```powershell
cd C:\Users\zhc\runoob-flask-test
.\.venv\Scripts\Activate.ps1
python app.py
```

服务监听 `http://127.0.0.1:5000`，启动时会自动创建 `app.db` 和 `items` 表。终端出现 `Running on http://127.0.0.1:5000` 即启动成功，按 `Ctrl+C` 停止。

如果 5000 端口被别的进程占用（Windows 上常见于之前没关干净的 Python），先查再结束：

```powershell
netstat -ano | findstr :5000
taskkill /F /PID <上面的 PID>
```

## 接口约定

所有接口返回统一结构：

```json
{"code": 0, "data": ..., "msg": "ok"}
```

- `code`：`0` 表示成功；失败时为对应的 HTTP 状态码（400 / 404 / 405 / 500）。
- `data`：成功时的数据，失败时为 `null`。
- `msg`：结果说明，失败时写明原因。

### 接口列表

| 方法 | 路径 | 参数 | 返回示例 |
| --- | --- | --- | --- |
| GET | `/api/items` | 无 | `{"code":0,"data":[{"id":1,"title":"写接口文档","done":false,"created_at":"2026-11-12T16:51:46+08:00","summary":"把四个接口和错误码补齐","tag":"项目"}],"msg":"ok"}` |
| POST | `/api/items` | body：`title` 必填；`done`、`summary`、`tag`、`priority`、`dueDate`、`dueTime`、`estimateMinutes`、`steps`、`note` 可选 | `201` `{"code":0,"data":{"id":1,"title":"写接口文档","done":false,"created_at":"2026-11-12T16:51:46+08:00","extra字段同上"},"msg":"创建成功"}` |
| PUT | `/api/items/<id>` | path：`id` 整数；body：任一可写字段，至少给一个 | `{"code":0,"data":{"id":1,"title":"写接口文档","done":true,"created_at":"..."},"msg":"修改成功"}` |
| DELETE | `/api/items/<id>` | path：`id` 整数 | `{"code":0,"data":{"id":1},"msg":"删除成功"}` |

> 为了兼容前端的任务编辑面板，`summary`、`tag`、`priority`、`dueDate`、`dueTime`、`estimateMinutes`、`steps`、`note` 这些附加字段统一存进 `items.extra`（JSON 文本），GET 时展开合并到返回对象里。

### 参数校验

- `title`：必须存在、必须是字符串、去掉首尾空格后不能为空、长度不超过 50 个字符。
- `done`：可选，必须是布尔值 `true` / `false`。
- `summary` ≤ 200 字符；`tag` 只能是 `学习`、`项目`、`生活`、`复盘`；`priority` 只能是 `high`、`medium`、`low`；`note` ≤ 2000 字符。
- `estimateMinutes`：0 到 600 的整数。
- `steps`：字符串数组，最多 50 条，每条不超过 200 字符。
- `dueDate`：`YYYY-MM-DD`；`dueTime`：`HH:MM`。
- 请求体不是合法 JSON、缺少字段、类型不对时返回 `400`，并在 `msg` 中写明具体原因，服务不会中断。

### 错误返回

| 状态码 | 场景 | 示例 |
| --- | --- | --- |
| 400 | 请求体缺失、字段缺失、字段类型错误 | `{"code":400,"data":null,"msg":"缺少字段 title"}` |
| 404 | 记录不存在或接口路径不存在 | `{"code":404,"data":null,"msg":"记录不存在"}` |
| 405 | 请求方法不允许 | `{"code":405,"data":null,"msg":"请求方法不允许"}` |
| 500 | 未捕获的服务器异常 | `{"code":500,"data":null,"msg":"服务器内部错误"}` |

所有错误都以 JSON 返回，不会把 HTML 报错页面返回给客户端。未捕获异常会写入服务端日志，同时返回统一结构的 500。

### 跨域

前端页面和接口不同源（例如页面在 `127.0.0.1:8000`，接口在 `127.0.0.1:5000`），浏览器会先做 CORS 预检。服务端统一处理：

- `after_request` 回显请求的 `Origin`，设置 `Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS`、`Access-Control-Allow-Headers: Content-Type`、`Access-Control-Max-Age: 86400`、`Vary: Origin`。
- `OPTIONS /api/items` 和 `OPTIONS /api/items/<id>` 返回 `204`，让预检通过。

验证预检：

```powershell
curl.exe -i -X OPTIONS http://127.0.0.1:5000/api/items -H "Origin: http://localhost:8000" -H "Access-Control-Request-Method: POST"
```

响应应为 `204`，并带 `Access-Control-Allow-Origin: http://localhost:8000`。

## 数据存储

数据保存在项目根目录的 `app.db`（SQLite 单文件数据库），表结构：

```sql
CREATE TABLE items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    extra      TEXT    NOT NULL DEFAULT '{}'
);
```

旧库没有 `extra` 列时，启动会自动执行 `ALTER TABLE items ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'`，已有数据不受影响。停止服务再启动，数据保持不变。

## 接口调用示例

Windows PowerShell 中 `curl` 是 `Invoke-WebRequest` 的别名，调用 curl 时写 `curl.exe`。GET、DELETE 可以直接用命令行：

```powershell
curl.exe -i http://127.0.0.1:5000/api/items
curl.exe -i -X DELETE http://127.0.0.1:5000/api/items/1
```

POST、PUT 需要带 JSON 请求体。PowerShell 5.1 直接内联 JSON 时引号可能被吞掉，推荐用 Postman，或把请求体写入 UTF-8 无 BOM 文件再发送：

```powershell
$json = '{"title":"写接口文档","summary":"把四个接口和错误码补齐","tag":"项目","steps":["读需求","写接口","自测"]}'
[IO.File]::WriteAllText("$PWD\body.json", $json, (New-Object System.Text.UTF8Encoding($false)))
curl.exe -i -X POST http://127.0.0.1:5000/api/items -H "Content-Type: application/json" --data-binary "@body.json"
```

验证缺字段时的返回：

```powershell
curl.exe -i -X POST http://127.0.0.1:5000/api/items -H "Content-Type: application/json" -d "{}"
```

应返回 `400 BAD REQUEST` 和 `{"code":400,"data":null,"msg":"缺少字段 title"}`。

## 部署到 PythonAnywhere

免费版够用，不需要信用卡。

已部署实例：https://sunmoonstars.pythonanywhere.com ，WSGI 指向 `/home/Sunmoonstars/runoob-flask-test`。

**1. 上传代码**

登录后打开 **Files**，新建目录 `runoob-flask-test`，进去点 **Upload a file**，选本机的 `app.py`。`pythonanywhere_wsgi.py` 是本地的 WSGI 配置示例，不用上传。

如果上传后目录仍是空的（网络中断时常见），可以在 **Bash console** 里直接写文件：`cat > ~/runoob-flask-test/app.py`，粘贴源码后按 `Ctrl+D`；或者把本地 `app.py` 做 gzip+base64 后粘贴执行 `base64 -d <<'EOF' | gunzip > ~/runoob-flask-test/app.py`。写完后用 `ls -l ~/runoob-flask-test/app.py` 确认大小。

**2. 安装依赖**

```bash
pip3 install --user flask==3.1.3
```

PythonAnywhere 自带 Flask，但版本可能偏旧；`app.json` 需要 Flask 2.2 以上，装 3.1.3 最稳。

**3. 建 Web 应用**

1. **Web** 标签 → **Add a new web app**
2. 选 **Manual configuration**（不要选 Flask 模板，模板会覆盖自己的代码）→ Python 3.10 及以上都行
3. 项目路径填 `/home/USERNAME/runoob-flask-test`（`USERNAME` 换成你的用户名）
4. 点 **WSGI configuration file** 链接，用 `pythonanywhere_wsgi.py` 的内容整体替换，只改 `USERNAME` 一处
5. 点 **Reload**；也可以在 Bash 里 `touch /var/www/USERNAME_pythonanywhere_com_wsgi.py` 触发重载

访问 `https://USERNAME.pythonanywhere.com/api/items`，返回 JSON 就成功了。

**说明**

- 数据库 `app.db` 会自动建在 `app.py` 同目录。`DB_PATH` 用 `__file__` 定位，不依赖启动目录和当前工作目录。
- PythonAnywhere 用 WSGI 托管，不会执行 `app.run()`；本地调试才用 `python app.py`。
- 免费实例有每日 CPU 秒数限制，作业演示足够；数据库是本地文件，迁移前记得备份 `app.db`。

`render.yaml` 保留作备选方案：部署到 Render 时它会按 `gunicorn app:app` 启动。

## 部署踩坑记录（实际遇到）

站点打开是 `Something went wrong :-(`，错误日志里是：

```text
ModuleNotFoundError: No module named 'app'
  File "/var/www/sunmoonstars_pythonanywhere_com_wsgi.py", line 7, in <module>
    from app import app as application
```

WSGI 里的路径是对的，但 `ls -la /home/USERNAME/runoob-flask-test/` 只有 `.` 和 `..`，`stat app.py` 报 `No such file or directory`——Files 里一次“看起来成功”的上传并没有真正落盘。

解决：

1. 在 **Bash console** 里直接写文件（`cat > ~/runoob-flask-test/app.py` 粘贴源码后 `Ctrl+D`），或把源码做 gzip+base64 后 `base64 -d <<'EOF' | gunzip > ~/runoob-flask-test/app.py`。
2. `ls -l ~/runoob-flask-test/app.py` 确认文件存在且有大小；`python3 -c "import app"` 确认能导入。
3. `touch /var/www/USERNAME_pythonanywhere_com_wsgi.py` 触发重载，再 `curl -sS https://USERNAME.pythonanywhere.com/api/items`。

返回 `{"code":0,"data":[],"msg":"ok"}` 即为成功；本实例的地址是 https://sunmoonstars.pythonanywhere.com/api/items 。

## 提交说明

仓库不包含虚拟环境和运行时数据库：

```
.venv/
__pycache__/
*.db
body.json
```

如需包含数据文件，删除 `.gitignore` 中的 `*.db`。
