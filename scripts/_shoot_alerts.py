# -*- coding: utf-8 -*-
"""重拍 docs/screenshots/alerts.png（一次性脚本，跑完即删）。

为什么用 agent-browser 而不是 Edge --screenshot：
  SPA 需先注入 localStorage 登录态、再点「实时直查」标签与「立即查询」按钮，
  Edge 的 --screenshot 无法执行交互；agent-browser 支持 eval / set viewport / click。

沙箱约束：服务与截图必须在同一条命令内完成（命令结束进程树被回收），
故本脚本自己起后端+前端、自己驱动浏览器、最后统统收掉。
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
VENV_PY = BASE / ".venv" / "Scripts" / "python.exe"
NODE = r"C:\Users\JJY\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
AB_JS = r"D:\ProgrammingTools\node-v18.0.0-win-x64\node_global\node_modules\agent-browser\bin\agent-browser.js"
OUT = BASE / "docs" / "screenshots" / "alerts.png"
TMP_OUT = BASE / "_s_alerts.png"
FRONTEND_PORT, GATEWAY_PORT = 3001, 8001


# ----------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------
def log(msg):
    print(f"[shoot] {msg}", flush=True)


def load_env():
    env = os.environ.copy()
    p = BASE / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    env.setdefault("DEV_API_KEY", "ak_dev_local")
    # 单体模式：三服务同进程，互调走网关前缀
    env["GATEWAY_PORT"] = str(GATEWAY_PORT)
    env["PLANNER_SERVICE_URL"] = f"http://127.0.0.1:{GATEWAY_PORT}/planner"
    env["SENSE_SERVICE_URL"] = f"http://127.0.0.1:{GATEWAY_PORT}/sense"
    env["PYTHONPATH"] = f"{BASE};{BASE / 'services' / 'gateway'}"
    env["CJH_MODE"] = "single"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def port_open(port, path="/"):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    except OSError:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def wait_port(port, path, name, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if port_open(port, path):
            log(f"{name} :{port} 就绪（{time.time() - t0:.1f}s）")
            return True
        time.sleep(1.5)
    return False


def ab(env, *args, timeout=180, quiet=False):
    cmd = [NODE, AB_JS, *args]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env)
    if not quiet:
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if out:
            log(f"  $ {' '.join(args[:2])} -> {out[:300]}")
        if r.returncode != 0 and err:
            log(f"  !! rc={r.returncode} {err[:300]}")
    return r


# ----------------------------------------------------------------------
# 页面交互用 JS
# ----------------------------------------------------------------------
JS_SET_AUTH = (
    "localStorage.setItem('cjh_auth', JSON.stringify("
    "{{token:'{token}',username:'admin',role:'admin'}})); 'auth-set'"
)

JS_CLICK = """(() => {{
  const t = {label};
  const leaves = [...document.querySelectorAll('*')].filter(
    e => e.children.length === 0 && (e.textContent || '').trim() === t);
  if (!leaves.length) return 'not-found';
  const el = leaves[leaves.length - 1];
  let n = el;
  for (let i = 0; i < 6 && n; i++) {{
    if (n.tagName === 'BUTTON' || n.getAttribute('role') === 'tab' ||
        n.tagName === 'A' || n.tagName === 'LI') break;
    n = n.parentElement;
  }}
  (n || el).click();
  return 'clicked:' + (n || el).tagName;
}})()"""


def main():
    procs = []
    env = load_env()

    # 0) 离线签发 admin token（不触碰任何用户数据；与 /auth/login 同一签发函数）
    sys.path.insert(0, str(BASE))
    from shared.middleware.session import SignedSession  # noqa: E402
    secret = env.get("SESSION_SECRET") or env.get("DEV_API_KEY") or "ak_dev_local"
    token = SignedSession.encode({"username": "admin", "role": "admin"}, secret, 7200)
    log(f"admin token 已签发（secret 来源：{'SESSION_SECRET' if env.get('SESSION_SECRET') else 'DEV_API_KEY'}）")

    try:
        # 1) 后端（网关单体）
        log_dir = BASE / ".logs"
        log_dir.mkdir(exist_ok=True)
        logf = log_dir / "_shoot_be.log"
        procs.append(subprocess.Popen(
            [str(VENV_PY), "-m", "uvicorn", "main:app", "--app-dir", str(BASE / "services" / "gateway"),
             "--host", "127.0.0.1", "--port", str(GATEWAY_PORT)],
            cwd=str(BASE / "services" / "gateway"), env=env,
            stdout=open(logf, "w", encoding="utf-8"), stderr=subprocess.STDOUT))
        log(f"后端已起 PID={procs[-1].pid}")
        if not wait_port(GATEWAY_PORT, "/health", "后端"):
            log("后端未就绪，放弃")
            return 1

        # 2) 前端 dev server
        npm = "npm.cmd" if os.name == "nt" else "npm"
        fe_env = env.copy()
        fe_env.pop("NODE_OPTIONS", None)
        procs.append(subprocess.Popen(
            [npm, "run", "dev"], cwd=str(BASE / "frontend"), env=fe_env, shell=(os.name == "nt"),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT))
        log(f"前端已起 PID={procs[-1].pid}")
        if not wait_port(FRONTEND_PORT, "/", "前端", timeout=180):
            log("前端未就绪，放弃")
            return 1

        # 3) 驱动浏览器
        ab(env, "close", quiet=True)
        ab(env, "set", "viewport", "1440", "1150")
        ab(env, "open", f"http://localhost:{FRONTEND_PORT}/alerts", timeout=120)
        ab(env, "wait", "2000")

        r = ab(env, "eval", JS_SET_AUTH.format(token=token))
        if "auth-set" not in (r.stdout or ""):
            log("登录态注入失败")
            return 1
        ab(env, "reload")
        ab(env, "wait", "3000")

        log("点击「实时直查」")
        ab(env, "eval", JS_CLICK.format(label="'实时直查'"))
        ab(env, "wait", "1500")

        log("点击「立即查询」")
        ab(env, "eval", JS_CLICK.format(label="'立即查询'"))
        ab(env, "wait", "4000")

        # 4) 截图（视口尺寸，与既有 1440x1150 一致）
        if TMP_OUT.exists():
            TMP_OUT.unlink()
        ab(env, "screenshot", str(TMP_OUT).replace("\\", "/"), timeout=120)
        if not TMP_OUT.exists():
            log("截图未生成")
            return 1
        log(f"截图已生成：{TMP_OUT} ({TMP_OUT.stat().st_size} 字节)")

        # 5) 覆盖目标图
        shutil.copy2(TMP_OUT, OUT)
        log(f"已覆盖 {OUT} ({OUT.stat().st_size} 字节)")
        return 0

    finally:
        ab(env, "close", quiet=True)
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        log("服务与浏览器已回收")


if __name__ == "__main__":
    sys.exit(main())
