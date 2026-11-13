# PythonAnywhere 的 WSGI 配置文件示例。
# 用法：Web 标签页 → 点 WSGI configuration file 链接 → 用下面的内容整体替换，
# 把 USERNAME 换成你的 PythonAnywhere 用户名（只改这一处），保存后点 Reload。
import sys

path = "/home/USERNAME/runoob-flask-test"
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application
