# -*- coding: utf-8 -*-
"""
企业智行 · Corporate Journey Hub —— 一键启动 · 统一控制台

设计目标：
  - 双击 start.bat 即用：环境自检 → 依赖增量安装 → 后台启动 → 健康检查 → 开浏览器
  - 统一控制台：不再弹多个窗口，单窗口实时状态面板 + 交互菜单
      [1] 启动全部  [2] 停止全部  [3] 重启全部
      [4] 查看服务日志  [5] 打开日志目录  [6] 打开工作台
      [7] 刷新状态  [0] 退出（服务继续后台运行）
  - 命令行模式：python launcher.py stop | restart | status | start
  - 后端/前端均 detached 后台运行，日志统一落盘 .logs/
  - 停止策略：先优雅关闭（不带 /F），2 秒后对残留强杀
  - 依赖增量检测：requirements.txt 内容变化才重装，启动更快

实战踩坑（勿删，参照 AI元年 ai-year-launcher skill）：
  1. start.bat 只做纯 ASCII 壳，中文逻辑全放本文件（cmd 按 GBK 解析批处理）。
  2. netstat 输出是本地编码（GBK）：必须 capture_output 拿字节再
     decode("utf-8", errors="ignore")——只解析端口和 PID（纯 ASCII）。
  3. 健康检查超时必须打印对应服务日志尾部，用户能立刻看到崩因。
  4. detached 进程在 AI 沙箱测试中可能被收割，属测试环境行为，非本文件 bug。
"""
import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与常量：无论源码还是 exe，均按自身所在目录定位资源
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

FRONTEND_DIR = BASE_DIR / "frontend"
VENV_DIR = BASE_DIR / ".venv"
VENV_PY = VENV_DIR / "Scripts" / "python.exe"
REQ_FILE = BASE_DIR / "requirements.txt"
RUN_DIR = BASE_DIR / ".run"
LOG_DIR = BASE_DIR / ".logs"

APP_TITLE = "企业智行 · Corporate Journey Hub"

# (名称, 展示名, 服务目录, 端口, 日志名)
BACKENDS = [
    ("journey", "行智 · Journey Hub", "services/journey-hub", 8001, "journey.log"),
    ("planner", "策程 · Planner Core", "services/planner-core", 8002, "planner.log"),
    ("sense", "感知 · Sense Engine", "services/sense-engine", 8003, "sense.log"),
]
FRONTEND_PORT = 3001          # 与 vite.config.js 一致
FRONTEND_LOG = "frontend.log"

APP_URL = f"http://localhost:{FRONTEND_PORT}/"
HEALTH_TIMEOUT = 90           # 健康检查最长轮询秒数
IS_WIN = sys.platform == "win32"

# ---------------------------------------------------------------------------
# 控制台颜色（Windows 10+ VT；非 TTY 自动降级为无色）
# ---------------------------------------------------------------------------
if IS_WIN:
    os.system("")  # 触发 ANSI 支持启用
_TTY = False
try:
    _TTY = sys.stdout.isatty()
except Exception:
    pass
if _TTY and IS_WIN:
    try:
        import ctypes
        _k = ctypes.windll.kernel32
        _h = _k.GetStdHandle(-11)
        _m = ctypes.c_uint32()
        if _k.GetConsoleMode(_h, ctypes.byref(_m)):
            _k.SetConsoleMode(_h, _m.value | 0x0004)
    except Exception:
        pass

C_GREEN = "\033[92m" if _TTY else ""
C_RED = "\033[91m" if _TTY else ""
C_YELLOW = "\033[93m" if _TTY else ""
C_CYAN = "\033[96m" if _TTY else ""
C_DIM = "\033[90m" if _TTY else ""
C_RESET = "\033[0m" if _TTY else ""


def log(msg: str = ""):
    print(msg, flush=True)


def step(title: str):
    log()
    log(f"{C_CYAN}" + "=" * 60 + C_RESET)
    log(f"{C_CYAN}{title}{C_RESET}")
    log(f"{C_CYAN}" + "=" * 60 + C_RESET)


# ---------------------------------------------------------------------------
# 基础探测
# ---------------------------------------------------------------------------
def is_port_alive(port: int, path: str = "/health", timeout: int = 2) -> bool:
    """检测端口是否返回 200（前端无 /health，path 传 '/'）"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _pids_on_port(port: int) -> list:
    """解析 netstat 返回监听该端口的 PID 列表。

    netstat 输出为本地编码（GBK）：按字节读取后 errors="ignore" 解码，
    只解析端口与 PID（纯 ASCII），避免控制台编码差异导致解析失败。
    """
    if not IS_WIN:
        return []
    try:
        out_b = subprocess.run(["netstat", "-ano"], capture_output=True).stdout or b""
    except Exception:
        return []
    out = out_b.decode("utf-8", errors="ignore")
    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, state, pid = parts[1], parts[3].upper(), parts[4]
        if state == "LISTENING" and local.endswith(f":{port}"):
            if pid.isdigit() and int(pid) != 0 and pid not in pids:
                pids.append(pid)
    return pids


def service_alive(entry):
    """entry: (port, health_path) → bool"""
    port, path = entry
    return is_port_alive(port, path)


# ---------------------------------------------------------------------------
# 环境与依赖（增量检测）
# ---------------------------------------------------------------------------
def get_python() -> str:
    """真实 Python 解释器路径（打包 exe 后 sys.executable 指向 exe 自身）。"""
    if getattr(sys, "frozen", False):
        p = shutil.which("python") or shutil.which("python3")
        if not p:
            raise RuntimeError("未找到 python，请安装 Python 3.10+ 并加入 PATH")
        return p
    return sys.executable


def check_python():
    if sys.version_info < (3, 10):
        raise RuntimeError(f"需要 Python >= 3.10，当前为 {sys.version.split()[0]}")
    log(f"{C_GREEN}[OK]{C_RESET} Python {sys.version.split()[0]}")


def _file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _pip_install(args: list, quiet: bool = False):
    """pip 执行统一参数：禁版本检查/禁交互/短超时，默认显示进度（避免看似卡住）。"""
    extra = ["--no-input", "--disable-pip-version-check", "--retries", "2", "--timeout", "15"]
    if quiet:
        extra.append("-q")
    run([str(VENV_PY), "-m", "pip"] + args + extra)


def ensure_venv():
    """虚拟环境 + 后端依赖：requirements.txt 哈希变化才重装。"""
    py = get_python()
    marker = VENV_DIR / ".req_hash"
    want = _file_hash(REQ_FILE) if REQ_FILE.exists() else ""
    if not VENV_PY.exists():
        step("创建虚拟环境并安装后端依赖（首次较慢，进度见下方输出）")
        if not REQ_FILE.exists():
            raise RuntimeError(f"未找到依赖文件: {REQ_FILE}")
        run([py, "-m", "venv", str(VENV_DIR)])
        _pip_install(["install", "--upgrade", "pip"])
        _pip_install(["install", "-r", str(REQ_FILE)])
        marker.write_text(want)
        log(f"{C_GREEN}[OK]{C_RESET} 后端依赖安装完成")
    elif marker.exists() and marker.read_text() == want:
        log(f"{C_GREEN}[OK]{C_RESET} 后端依赖无变化，跳过安装")
    else:
        first = not marker.exists()
        if first:
            log(f"{C_YELLOW}[..]{C_RESET} 首次运行：校验一次依赖（已装过的不会重下，慢时约 1-2 分钟，仅此一次）...")
        else:
            log(f"{C_YELLOW}[..]{C_RESET} requirements.txt 有变化，增量安装中...")
        _pip_install(["install", "-r", str(REQ_FILE)])
        marker.write_text(want)
        log(f"{C_GREEN}[OK]{C_RESET} 后端依赖校验完成")


def ensure_frontend():
    node_modules = FRONTEND_DIR / "node_modules"
    if node_modules.exists() and any(node_modules.iterdir()):
        log(f"{C_GREEN}[OK]{C_RESET} 前端依赖已存在，跳过安装")
        return
    step("安装前端依赖（首次较慢）")
    npm = "npm.cmd" if IS_WIN else "npm"
    run([npm, "install"], cwd=FRONTEND_DIR, env=os.environ.copy())
    log(f"{C_GREEN}[OK]{C_RESET} 前端依赖安装完成")


def run(cmd, cwd=None, env=None, check=True):
    """统一执行命令；失败抛 RuntimeError 带出输出。"""
    log(f"  {C_DIM}> {' '.join(str(c) for c in cmd)}{C_RESET}")
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError(f"找不到可执行文件: {cmd[0]} —— {e}")
    if check and proc.returncode != 0:
        out = (proc.stdout or "") + (proc.stderr or "")
        raise RuntimeError(f"命令失败(退出码 {proc.returncode}):\n{out[-2000:]}")
    return proc


# ---------------------------------------------------------------------------
# .env 与后端子进程环境（对齐 scripts/start_local.py）
# ---------------------------------------------------------------------------
def load_env_file() -> dict:
    env = {}
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return env
    try:
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if key.strip() and value and not value.startswith("sk-your"):
                env[key.strip()] = value
    except Exception:
        pass
    return env


def _backend_env(service_dir: str) -> dict:
    env = os.environ.copy()
    env.update(load_env_file())
    workdir = BASE_DIR / service_dir
    env["PYTHONPATH"] = f"{BASE_DIR};{workdir}" + (
        f";{env['PYTHONPATH']}" if env.get("PYTHONPATH") else ""
    )
    env["PLANNER_SERVICE_URL"] = "http://127.0.0.1:8002"
    env["SENSE_SERVICE_URL"] = "http://127.0.0.1:8003"
    env.setdefault("DEV_API_KEY", "ak_dev_local")
    return env


def _spawn_detached(cmd: list, cwd: Path, log_name: str, env: dict = None):
    """detached 后台启动：关掉本窗口进程仍存活，日志追加落盘。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(LOG_DIR / log_name, "ab")
    kwargs = {"cwd": str(cwd), "stdout": logf, "stderr": subprocess.STDOUT,
              "stdin": subprocess.DEVNULL}
    if IS_WIN:
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, env=env, **kwargs)


# ---------------------------------------------------------------------------
# 启动（按需：已运行的服务跳过，不做破坏性重启）
# ---------------------------------------------------------------------------
def start_backend(name: str, display: str, service_dir: str, port: int, log_name: str) -> bool:
    if is_port_alive(port):
        log(f"  {C_GREEN}[跳过]{C_RESET} {display} :{port} 已在运行")
        return False
    cmd = [str(VENV_PY), "-m", "uvicorn", "api.main:app",
           "--app-dir", str(BASE_DIR / service_dir),
           "--host", "127.0.0.1", "--port", str(port)]
    proc = _spawn_detached(cmd, BASE_DIR / service_dir, log_name, env=_backend_env(service_dir))
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / f"{name}.pid").write_text(str(proc.pid))
    log(f"  {C_GREEN}[启动]{C_RESET} {display} :{port} PID={proc.pid}")
    return True


def start_frontend() -> bool:
    if is_port_alive(FRONTEND_PORT, path="/"):
        log(f"  {C_GREEN}[跳过]{C_RESET} 前端工作台 :{FRONTEND_PORT} 已在运行")
        return False
    npm = "npm.cmd" if IS_WIN else "npm"
    env = os.environ.copy()
    # 清空 NODE_OPTIONS，避免 --require 注入干扰 Vite 依赖优化
    env.pop("NODE_OPTIONS", None)
    proc = _spawn_detached([npm, "run", "dev"], FRONTEND_DIR, FRONTEND_LOG, env=env)
    log(f"  {C_GREEN}[启动]{C_RESET} 前端工作台 :{FRONTEND_PORT} PID={proc.pid}（无窗口，日志落盘）")
    return True


def start_all():
    step("启动服务（后台 · 已运行的自动跳过）")
    ensure_venv()
    ensure_frontend()
    started = False
    for name, display, service_dir, port, log_name in BACKENDS:
        started |= start_backend(name, display, service_dir, port, log_name)
    started |= start_frontend()
    if not started:
        log(f"  {C_GREEN}[OK]{C_RESET} 全部服务已在运行，无需启动。")


# ---------------------------------------------------------------------------
# 停止（先优雅后强杀）
# ---------------------------------------------------------------------------
def _terminate_pids(pids: list):
    for pid in pids:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True)  # 优雅关闭
        else:
            subprocess.run(["kill", str(pid)], capture_output=True)
    time.sleep(2)
    for pid in pids:  # 残留强杀
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True)


def stop_all():
    step("停止全部服务")
    stopped = 0
    targets = [(display, port) for _, display, _, port, _ in BACKENDS] + [("前端工作台", FRONTEND_PORT)]
    for display, port in targets:
        pids = _pids_on_port(port)
        if pids:
            _terminate_pids(pids)
            log(f"  {C_GREEN}[停止]{C_RESET} {display} :{port} PID={', '.join(pids)}")
            stopped += 1
        else:
            log(f"  {C_DIM}[--]{C_RESET} {display} :{port} 未在运行")
    # PID 文件兜底清理（兼容 scripts/start_local.py 落的 .run/*.pid）
    if RUN_DIR.exists():
        for pf in RUN_DIR.glob("*.pid"):
            try:
                pid = pf.read_text().strip()
                if pid.isdigit():
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                pf.unlink(missing_ok=True)
            except Exception:
                pass
    if stopped:
        time.sleep(1)
    log(f"{C_GREEN}[OK]{C_RESET} 停止完成（共 {stopped} 个）。" if stopped else "没有正在运行的服务。")


# ---------------------------------------------------------------------------
# 状态面板
# ---------------------------------------------------------------------------
def status_table() -> bool:
    entries = [(display, port, "/health", LOG_DIR / log_name)
               for _, display, _, port, log_name in BACKENDS]
    entries.append(("前端工作台", FRONTEND_PORT, "/", LOG_DIR / FRONTEND_LOG))
    log(f"{C_CYAN}── 服务状态 {'─' * 40}{C_RESET}")
    all_up = True
    for display, port, path, logf in entries:
        alive = is_port_alive(port, path)
        all_up &= alive
        pids = _pids_on_port(port) if alive else []
        pid_s = f"PID {pids[0]}" if pids else ""
        if alive:
            mark, color = "运行中", C_GREEN
        else:
            mark, color = "未启动", C_RED
        tail = f"{C_DIM}日志 {logf.name}{C_RESET}" if logf.exists() else ""
        log(f"  {color}[{mark}]{C_RESET} {display:<22} :{port:<6} {pid_s:<12} {tail}")
    return all_up


def tail_log(name: str, n: int = 40):
    logf = LOG_DIR / name
    if not logf.exists():
        log(f"{C_YELLOW}[提示]{C_RESET} 日志文件不存在: {logf}（服务可能尚未启动过）")
        return
    step(f"日志 · {name}（最后 {n} 行）")
    try:
        lines = logf.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
        for ln in lines:
            print(ln, flush=True)
    except Exception as e:
        log(f"{C_RED}[错误]{C_RESET} 读取日志失败: {e}")


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------
def wait_for_health() -> bool:
    step(f"健康检查（最长轮询 {HEALTH_TIMEOUT} 秒）")
    entries = [(display, port, "/health", LOG_DIR / log_name)
               for _, display, _, port, log_name in BACKENDS]
    entries.append(("前端工作台", FRONTEND_PORT, "/", LOG_DIR / FRONTEND_LOG))
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        if all(is_port_alive(p, pa) for _, p, pa, _ in entries):
            log(f"  {C_GREEN}[OK]{C_RESET} 全部服务就绪")
            return True
        time.sleep(2)
    log(f"  {C_YELLOW}[警告]{C_RESET} 超时未全部就绪，未就绪服务的日志尾部：")
    for display, port, path, logf in entries:
        if not is_port_alive(port, path):
            log(f"  ── {display} :{port} ──")
            try:
                if logf.exists():
                    for ln in logf.read_text(encoding="utf-8", errors="ignore").splitlines()[-15:]:
                        print("    " + ln, flush=True)
                else:
                    log("    （无日志文件）")
            except Exception:
                pass
    return False


def open_browser():
    try:
        webbrowser.open(APP_URL)
        log(f"{C_GREEN}[OK]{C_RESET} 已打开工作台: {APP_URL}")
    except Exception as e:
        log(f"{C_YELLOW}[提示]{C_RESET} 无法自动打开浏览器，请手动访问 {APP_URL}（{e}）")


# ---------------------------------------------------------------------------
# 统一控制台（交互菜单）
# ---------------------------------------------------------------------------
def interactive_menu():
    actions = (
        "[1] 启动全部   [2] 停止全部   [3] 重启全部\n"
        "[4] 查看服务日志   [5] 打开日志目录   [6] 打开工作台\n"
        "[7] 刷新状态   [0] 退出（服务继续后台运行）"
    )
    while True:
        log()
        all_up = status_table()
        if all_up:
            log(f"  {C_GREEN}✓ 全部服务运行中{C_RESET}  工作台: {APP_URL}")
        log()
        log(actions)
        try:
            choice = input("请选择: ").strip()
        except (EOFError, KeyboardInterrupt):
            log("\n已退出（服务继续后台运行）。")
            return
        if choice == "1":
            start_all()
            wait_for_health()
            open_browser()
        elif choice == "2":
            stop_all()
        elif choice == "3":
            stop_all()
            time.sleep(1)
            start_all()
            wait_for_health()
            open_browser()
        elif choice == "4":
            names = [log_name for _, _, _, _, log_name in BACKENDS] + [FRONTEND_LOG]
            disp = [d for _, d, _, _, _ in BACKENDS] + ["前端工作台"]
            for i, d in enumerate(disp, 1):
                log(f"  [{i}] {d} ({names[i - 1]})")
            try:
                idx = input("查看哪个日志（回车取消）: ").strip()
                if idx.isdigit() and 1 <= int(idx) <= len(names):
                    tail_log(names[int(idx) - 1])
            except (EOFError, KeyboardInterrupt):
                pass
        elif choice == "5":
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if IS_WIN:
                os.startfile(str(LOG_DIR))  # noqa: S606
            else:
                run(["xdg-open", str(LOG_DIR)], check=False)
        elif choice == "6":
            open_browser()
        elif choice == "7":
            continue  # 回到循环顶自动刷新状态
        elif choice == "0":
            log("已退出（服务继续后台运行；停止请运行 python launcher.py stop）。")
            return


def one_shot_start(enter_menu: bool = True):
    """完整一键链路：环境 → 依赖 → 启动 → 健康检查 → 开页面 → 控制台。"""
    log(f"{APP_TITLE} —— 一键启动 · 统一控制台")
    try:
        step("1/环境检查")
        check_python()

        step("2/依赖检查（增量）")
        ensure_venv()
        ensure_frontend()

        backends_up = all(is_port_alive(b[3]) for b in BACKENDS)
        if backends_up and is_port_alive(FRONTEND_PORT, path="/"):
            log()
            log(f"{C_GREEN}[OK]{C_RESET} 检测到全套服务已在运行，直接进入控制台。")
        else:
            start_all()
            wait_for_health()
            open_browser()

        if enter_menu:
            interactive_menu()
        else:
            log("\n服务已在后台运行；停止请运行 python launcher.py stop")
    except RuntimeError as e:
        log()
        log("=" * 60)
        log(f"{C_RED}[启动失败]{C_RESET}")
        log(str(e))
        log("=" * 60)
        _pause_if_tty()
        sys.exit(1)
    except KeyboardInterrupt:
        log("\n已取消。")
        sys.exit(0)


def _pause_if_tty():
    try:
        if sys.stdin.isatty() and sys.stdout.isatty():
            input("\n按 Enter 关闭窗口。")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI 入口：start（默认）/ stop / restart / status
# ---------------------------------------------------------------------------
def cli():
    action = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "start"
    if action == "stop":
        stop_all()
        _pause_if_tty()
    elif action == "restart":
        stop_all()
        time.sleep(1)
        one_shot_start(enter_menu=False)
        _pause_if_tty()
    elif action == "status":
        all_up = status_table()
        log()
        log(f"工作台: {APP_URL}")
        _pause_if_tty()
        sys.exit(0 if all_up else 1)
    else:  # start
        one_shot_start(enter_menu=True)


if __name__ == "__main__":
    cli()
