"""前后端 API 契约对账 —— 防止「前端调了后端没有的路由」这类死链复发。

背景：v3 切型把旧三层微服务（journey-hub / planner-core / sense-engine / gateway）
整体移除，收敛为单服务 services/core。但前端仍沿用 `/api/journey`、`/api/planner`、
`/api/sense` 三个代理前缀（见 frontend/vite.config.js），其中被重写掉的路径里
有相当一部分在 v3 内核已无对应路由 —— 表现为整页 404。

本脚本的判定口径：
  1. 后端路由真相 = FastAPI app.openapi()['paths']（惰性 _IncludedRouter 不参与，故不用 app.routes）。
  2. 前端调用点 = frontend/src/api/*.js 里 get/post/put/del/postEmpty/fetch 的字面量 URL。
  3. 归一化：剥离 `/api/{journey,planner,sense}` 代理前缀；路径段参数 → `{p}`；
     查询串插值（`${qs}` 之类）删除，避免误判。

用法（仓库根目录）：
    ./.venv/Scripts/python.exe scripts/check_api_contract.py
退出码：0 = 无死链；1 = 存在死链（可用于 CI / 提交前检查）。
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "services"))
sys.path.insert(0, ROOT)

from core.main import app  # noqa: E402

PROXY_PREFIX = re.compile(r"^/api/(journey|planner|sense)")
HTTP_FNS = {"get": "GET", "post": "POST", "put": "PUT", "del": "DELETE", "postEmpty": "POST"}


def backend_routes():
    """后端权威路由集合，形如 {('GET', '/trips/{p}')}。"""
    routes = set()
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method in ("get", "post", "put", "delete", "patch"):
                routes.add((method.upper(), re.sub(r"\{[^}]+\}", "{p}", path)))
    return routes


def _cut_query_template(url):
    """截断尾部「查询串模板表达式」。

    形如 ``/guides${q ? `?${q}` : ''}`` 的写法里含嵌套反引号，正则无法稳妥匹配；
    但规律很稳：**路径段参数的前一个字符一定是 `/`，查询串插值不是**。
    于是找到第一个「前面不是 /」的 ``${`` 就地截断。
    """
    for m in re.finditer(r"\$\{", url):
        if m.start() == 0 or url[m.start() - 1] != "/":
            return url[: m.start()]
    return url


def normalize(url):
    """把前端字面量 URL 归一化成可与后端路由比较的形式。"""
    url = url.replace("${BASE_URL}", "")
    url = _cut_query_template(url)
    url = PROXY_PREFIX.sub("", url)
    url = url.split("?")[0]                 # 丢弃查询串
    url = re.sub(r"\$\{[^}]+\}", "{p}", url)  # 路径段参数：/trips/${id}/checklist
    url = re.sub(r"\{[^}]+\}", "{p}", url)    # 已经写死的 {id}
    return url.rstrip("/") or "/"


def frontend_calls():
    """前端全部调用点，形如 [(文件, 方法, 归一化路径)]。"""
    calls = []
    pattern = re.compile(r"""(get|post|put|del|postEmpty)\(\s*[`'"]([^`'"]+)""")
    for file in sorted(glob.glob(os.path.join(ROOT, "frontend/src/api/*.js"))):
        src = open(file, encoding="utf-8").read()
        for m in pattern.finditer(src):
            calls.append((os.path.basename(file), HTTP_FNS[m.group(1)], normalize(m.group(2))))
        for m in re.finditer(r"""fetch\(\s*[`'"]([^`'"]+)""", src):
            calls.append((os.path.basename(file), "GET", normalize(m.group(1))))
    return calls


def main():
    routes = backend_routes()
    calls = frontend_calls()
    dead = [c for c in calls if (c[1], c[2]) not in routes]

    print(f"后端路由 {len(routes)} 条；前端调用点 {len(calls)} 个\n")
    if dead:
        print("=== 死链（前端调用了后端不存在的路由）===")
        for file, method, path in dead:
            print(f"  {file:16} {method:7} {path}")
        print()
    print(f"结论：死链 {len(dead)} 个 / 调用点 {len(calls)} 个")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
