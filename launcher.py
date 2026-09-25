# -*- coding: utf-8 -*-
"""
企业智行 · Corporate Journey Hub —— 一键启动

设计目标：
  - 双击 start.bat 即用：环境自检 → 依赖增量安装 → 并行后台启动 → 增量健康检查 → 开浏览器
      ★ 默认（无参数）：启动完成即自动关窗，重复双击不会叠窗口
      ★ 三个服务默认合并为**一个进程**（单体模式，端口 8001）
  - 两种运行模式（随时切换）：
      ★ single（默认）：单体模式 —— services/gateway 把三个服务的 app 装配进**单进程单端口 8001**
      ★ micro        ：微服务模式 —— 行智 8001 / 策程 8002 / 感知 8003 各自独立进程
  - 命令行模式：python launcher.py [start|menu|stop|restart|status|clean|fresh] [single|micro]
  - 后端/前端均 detached 后台运行，日志统一落盘 .logs/
  - 启动策略：服务并行拉起（线程池），健康检查逐服务就绪即报，缩短冷启动等待
  - 停止策略：先优雅关闭（不带 /F），2 秒后对残留强杀；覆盖两种模式全部端口，不留孤儿进程
  - 依赖增量检测：requirements.txt 内容变化才重装，启动更快

日常只需两个入口：双击 `start.bat` 启动、双击 `停止.bat` 停止。
其余能力（常驻控制台 / 清数据 / 干净启动）仍可通过上面的命令行子命令使用。

实战踩坑（勿删，参照 AI元年 ai-year-launcher skill）：
  1. start.bat 只做纯 ASCII 壳，中文逻辑全放本文件（cmd 按 GBK 解析批处理）。
  2. netstat 输出是本地编码（GBK）：必须 capture_output 拿字节再
     decode("utf-8", errors="ignore")——只解析端口和 PID（纯 ASCII）。
  3. 健康检查超时必须打印对应服务日志尾部，用户能立刻看到崩因。
  4. detached 进程在 AI 沙箱测试中可能被收割，属测试环境行为，非本文件 bug。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
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
RESET_SCRIPT = BASE_DIR / "scripts" / "reset_data.py"
FRESH_FLAG = BASE_DIR / ".cjh_fresh"      # 存在 = 每次启动自动清空运行数据
BACKUP_DIR = BASE_DIR / ".backup"

APP_TITLE = "企业智行 · Corporate Journey Hub"

# (名称, 展示名, 服务目录(cwd), 端口, 日志名)
# v3 起：唯一后端 = Agent 内核（单进程单端口 8001），旧三层微服务已随切型移除
SINGLE_BACKENDS = [
    ("core", "企业智行 · Agent 内核（v3）", "services", 8001, "core.log"),
]
# 微服务模式已退役：保留别名兼容旧习惯，行为与单体一致
MICRO_BACKENDS = SINGLE_BACKENDS
MODES = {"single": SINGLE_BACKENDS, "micro": MICRO_BACKENDS}
MODE_ALIASES = {
    "single": "single", "mono": "single", "1": "single", "单体": "single", "单体模式": "single",
    "micro": "micro", "ms": "micro", "2": "micro", "微服务": "micro", "微服务模式": "micro",
}
MODE_LABELS = {"single": "单体模式（单进程 · 单端口 8001）", "micro": "微服务模式（3 端口 8001/8002/8003）"}
DEFAULT_MODE = MODE_ALIASES.get(os.getenv("CJH_MODE", "single").strip().lower(), "single")
FRONTEND_PORT = 3001          # 与 vite.config.js 一致
FRONTEND_LOG = "frontend.log"


def normalize_mode(value: str = None, fallback: str = None) -> str:
    """把命令行/菜单输入归一化为 single | micro。"""
    return MODE_ALIASES.get((value or "").strip().lower(), fallback or DEFAULT_MODE)


def backends_for(mode: str) -> list:
    return MODES.get(mode, SINGLE_BACKENDS)


def all_ports() -> list:
    """两种模式的全部端口（停止时全覆盖，避免切换模式后留下孤儿进程）。"""
    ports = []
    for bl in (SINGLE_BACKENDS, MICRO_BACKENDS):
        for _, _, _, port, _ in bl:
            if port not in ports:
                ports.append(port)
    ports.append(FRONTEND_PORT)
    return ports


def all_targets() -> list:
    """(展示名, 端口) 全集，供停止/状态使用。"""
    targets = []
    seen = set()
    for bl in (SINGLE_BACKENDS, MICRO_BACKENDS):
        for _, display, _, port, _ in bl:
            if port not in seen:
                seen.add(port)
                targets.append((display, port))
    targets.append(("前端工作台", FRONTEND_PORT))
    return targets

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


def _listen_map() -> dict:
    """一次 netstat 拿到「端口 → 监听 PID 列表」映射，供 status/stop 复用。

    netstat 输出为本地编码（GBK）：按字节读取后 errors="ignore" 解码，
    只解析端口与 PID（纯 ASCII），避免控制台编码差异导致解析失败。
    """
    if not IS_WIN:
        return {}
    try:
        out_b = subprocess.run(["netstat", "-ano"], capture_output=True).stdout or b""
    except Exception:
        return {}
    out = out_b.decode("utf-8", errors="ignore")
    mapping = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, state, pid = parts[1], parts[3].upper(), parts[4]
        if state != "LISTENING" or not pid.isdigit() or int(pid) == 0:
            continue
        try:
            port = int(local.rsplit(":", 1)[-1])
        except ValueError:
            continue
        pids = mapping.setdefault(port, [])
        if pid not in pids:
            pids.append(pid)
    return mapping


def _pids_on_port(port: int) -> list:
    """解析 netstat 返回监听该端口的 PID 列表（单次调用，兼容旧调用方）。"""
    return _listen_map().get(port, [])


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


def _backend_env(service_dir: str, mode: str = DEFAULT_MODE) -> dict:
    env = os.environ.copy()
    env.update(load_env_file())
    workdir = BASE_DIR / service_dir
    env["PYTHONPATH"] = f"{BASE_DIR};{workdir}" + (
        f";{env['PYTHONPATH']}" if env.get("PYTHONPATH") else ""
    )
    if mode == "micro":
        # 微服务模式：行程/感知分别落在 8002 / 8003
        env["PLANNER_SERVICE_URL"] = "http://127.0.0.1:8002"
        env["SENSE_SERVICE_URL"] = "http://127.0.0.1:8003"
    else:
        # 单体模式：三服务同进程，内部互调走网关前缀（零代码改动）
        gw = SINGLE_BACKENDS[0][3]
        env["GATEWAY_PORT"] = str(gw)
        env["PLANNER_SERVICE_URL"] = f"http://127.0.0.1:{gw}/planner"
        env["SENSE_SERVICE_URL"] = f"http://127.0.0.1:{gw}/sense"
    env.setdefault("DEV_API_KEY", "ak_dev_local")
    return env


def _spawn_detached(cmd: list, cwd: Path, log_name: str, env: dict = None):
    """detached 后台启动：关掉本窗口进程仍存活，日志追加落盘。

    Windows 下除 DETACHED_PROCESS | NEW_PROCESS_GROUP 外，额外尝试
    CREATE_BREAKAWAY_FROM_JOB（0x01000000）——避免父进程/终端被回收时
    整棵进程树被作业对象连带杀掉（现象：服务已 startup complete，日志里
    却没有任何 shutdown 记录就没了）。作业对象不允许脱离时自动降级。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(LOG_DIR / log_name, "ab")
    kwargs = {"cwd": str(cwd), "stdout": logf, "stderr": subprocess.STDOUT,
              "stdin": subprocess.DEVNULL}
    if IS_WIN:
        base = 0x00000008 | 0x00000200          # DETACHED_PROCESS | NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(cmd, env=env, creationflags=base | 0x01000000, **kwargs)
        except OSError:
            log(f"  {C_DIM}（当前环境不允许脱离作业对象，降级为普通后台进程）{C_RESET}")
            return subprocess.Popen(cmd, env=env, creationflags=base, **kwargs)
    kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, env=env, **kwargs)


# ---------------------------------------------------------------------------
# 启动（按需：已运行的服务跳过，不做破坏性重启）
# ---------------------------------------------------------------------------
def start_backend(name: str, display: str, service_dir: str, port: int, log_name: str,
                  mode: str = DEFAULT_MODE) -> bool:
    if is_port_alive(port):
        log(f"  {C_GREEN}[跳过]{C_RESET} {display} :{port} 已在运行")
        return False
    # v3：Agent 内核入口是 core/main.py（--app-dir 指向 services/，core 包可解析）
    app_target = "core.main:app" if name == "core" else "api.main:app"
    cmd = [str(VENV_PY), "-m", "uvicorn", app_target,
           "--app-dir", str(BASE_DIR / service_dir),
           "--host", "127.0.0.1", "--port", str(port)]
    proc = _spawn_detached(cmd, BASE_DIR / service_dir, log_name, env=_backend_env(service_dir, mode))
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / f"{name}.pid").write_text(str(proc.pid))
    log(f"  {C_GREEN}[启动]{C_RESET} {display} :{port} PID={proc.pid}")
    return True


def start_frontend(mode: str = DEFAULT_MODE) -> bool:
    if is_port_alive(FRONTEND_PORT, path="/"):
        log(f"  {C_GREEN}[跳过]{C_RESET} 前端工作台 :{FRONTEND_PORT} 已在运行")
        return False
    npm = "npm.cmd" if IS_WIN else "npm"
    env = os.environ.copy()
    # 清空 NODE_OPTIONS，避免 --require 注入干扰 Vite 依赖优化
    env.pop("NODE_OPTIONS", None)
    # 告知 Vite 代理按哪种模式指向（single 单端口 / micro 三端口）
    env["CJH_MODE"] = mode
    proc = _spawn_detached([npm, "run", "dev"], FRONTEND_DIR, FRONTEND_LOG, env=env)
    log(f"  {C_GREEN}[启动]{C_RESET} 前端工作台 :{FRONTEND_PORT} PID={proc.pid}（无窗口，日志落盘）")
    return True


def start_all(mode: str = DEFAULT_MODE):
    backends = backends_for(mode)
    step(f"启动服务 · {MODE_LABELS.get(mode, mode)}（并行 · 已运行的自动跳过）")
    ensure_venv()
    ensure_frontend()
    with ThreadPoolExecutor(max_workers=len(backends) + 1) as ex:
        jobs = {ex.submit(start_backend, *b, mode): b for b in backends}
        jobs[ex.submit(start_frontend, mode)] = ("前端工作台",)
        started = False
        for fut in as_completed(jobs):
            who = jobs[fut][0]
            try:
                started |= bool(fut.result())
            except Exception as e:
                log(f"  {C_RED}[失败]{C_RESET} {who} 启动异常: {e}")
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
    # 两种模式的端口一起停：切过模式也不留孤儿进程
    targets = all_targets()
    listen = _listen_map()  # 一次 netstat 查全部端口
    for display, port in targets:
        pids = listen.get(port, [])
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
def status_table(mode: str = DEFAULT_MODE) -> bool:
    """状态面板：默认只看当前模式的端口，另附其他端口的残留提示。"""
    backends = backends_for(mode)
    entries = [(display, port, "/health", LOG_DIR / log_name)
               for _, display, _, port, log_name in backends]
    entries.append(("前端工作台", FRONTEND_PORT, "/", LOG_DIR / FRONTEND_LOG))
    listen = _listen_map()
    # 并行探活：4 个服务不再串行等（全挂时从最长 8s 降到约 1s）
    with ThreadPoolExecutor(max_workers=len(entries)) as ex:
        alive_flags = list(ex.map(lambda e: is_port_alive(e[1], e[2], timeout=1), entries))
    log(f"{C_CYAN}── 服务状态 · {MODE_LABELS.get(mode, mode)} {'─' * 20}{C_RESET}")
    all_up = True
    for (display, port, path, logf), alive in zip(entries, alive_flags):
        all_up &= alive
        pids = listen.get(port, []) if alive else []
        pid_s = f"PID {pids[0]}" if pids else ""
        if alive:
            mark, color = "运行中", C_GREEN
        else:
            mark, color = "未启动", C_RED
        tail = f"{C_DIM}日志 {logf.name}{C_RESET}" if logf.exists() else ""
        log(f"  {color}[{mark}]{C_RESET} {display:<22} :{port:<6} {pid_s:<12} {tail}")

    # 其他模式端口的残留提示（例如切到单体模式后 8002/8003 还占着）
    other = [(d, p) for d, p in all_targets() if p not in [e[1] for e in entries]]
    leftovers = [(d, p) for d, p in other if p in listen]
    if leftovers:
        log(f"  {C_YELLOW}[提示]{C_RESET} 检测到其他模式的端口仍在监听："
            + "，".join(f"{d}:{p}" for d, p in leftovers)
            + "（如需清理请执行 停止.bat 或 launcher.py stop）")
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
def wait_for_health(mode: str = DEFAULT_MODE) -> bool:
    step(f"健康检查（最长轮询 {HEALTH_TIMEOUT} 秒）")
    entries = [(display, port, "/health", LOG_DIR / log_name)
               for _, display, _, port, log_name in backends_for(mode)]
    entries.append(("前端工作台", FRONTEND_PORT, "/", LOG_DIR / FRONTEND_LOG))
    pending = {d: (p, pa, lf) for d, p, pa, lf in entries}
    t0 = time.time()
    # 增量轮询：谁先就绪先报谁，不再等最慢的一个
    while pending and time.time() - t0 < HEALTH_TIMEOUT:
        for d in list(pending):
            port, path, _ = pending[d]
            if is_port_alive(port, path, timeout=1):
                log(f"  {C_GREEN}[OK]{C_RESET} {d:<20} :{port} 就绪（{(time.time() - t0):.1f}s）")
                pending.pop(d)
        if pending:
            time.sleep(0.4)
    if not pending:
        log(f"  {C_GREEN}[OK]{C_RESET} 全部服务就绪（总耗时 {(time.time() - t0):.1f}s）")
        return True
    log(f"  {C_YELLOW}[警告]{C_RESET} 超时未就绪的服务：")
    for display, (port, path, logf) in pending.items():
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


# ---------------------------------------------------------------------------
# 对话记录清理（只清对话，不动行程等业务数据）
# ---------------------------------------------------------------------------
def _dev_api_key() -> str:
    """鉴权用的 API Key（与前端 X-API-Key 同源）：优先 .env 的 DEV_API_KEY。"""
    val = os.getenv("DEV_API_KEY", "").strip()
    if val:
        return val
    env_file = BASE_DIR / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("DEV_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "ak_dev_local"  # 开发后门默认值（非生产环境生效）


def reset_chat_history(mode: str = DEFAULT_MODE):
    """启动时清掉上一次的对话记录（服务端会话历史），行程等一概保留。

    前端那半（localStorage 快照）由工作台 URL 的 ?fresh=1 负责；
    这里负责服务端：清空 journey-hub 的 SessionManager 内存历史。
    服务不可用 / 鉴权失败时静默跳过 —— 对话清不掉不该挡住启动。
    """
    try:
        port = backends_for(normalize_mode(mode))[0][3]
        headers = {"X-API-Key": _dev_api_key()}
        url = f"http://127.0.0.1:{port}/agent/sessions"
        # 先列出活跃会话，逐个清掉（含 agent_hub 侧）
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
    except Exception:
        return  # 服务未就绪 / 端点不可用：静默跳过，?fresh=1 仍会清前端

    sids = [s.get("session_id") for s in (data or {}).get("sessions", []) if s.get("session_id")]
    if not sids:
        return
    cleared = 0
    for sid in sids:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/agent/session/{urllib.parse.quote(sid)}/clear",
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3):
                cleared += 1
        except Exception:
            pass
    if cleared:
        log(f"  {C_DIM}已清空 {cleared} 个会话的对话记录（行程等数据保留）{C_RESET}")


def open_browser(reset_chat: bool = False):
    """打开工作台；reset_chat=True 时带 ?fresh=1，让前端丢掉上一次的对话记录。

    注意：?fresh=1 只清「对话」（前端 localStorage 快照 + 服务端会话历史），
    行程 / 审批 / 报销 / 画像等业务数据一律保留 —— 这是与 run_reset() 的本质区别。
    """
    url = APP_URL + ("?fresh=1" if reset_chat else "")
    try:
        webbrowser.open(url)
        log(f"{C_GREEN}[OK]{C_RESET} 已打开工作台: {url}")
    except Exception as e:
        log(f"{C_YELLOW}[提示]{C_RESET} 无法自动打开浏览器，请手动访问 {url}（{e}）")


# ---------------------------------------------------------------------------
# 运行数据清理（干净启动 / 重置演示环境）
# ---------------------------------------------------------------------------
def _fresh_scope() -> str:
    """读取 .cjh_fresh 标记内容（runtime | full），默认 runtime。"""
    try:
        val = FRESH_FLAG.read_text(encoding="utf-8", errors="ignore").strip().lower()
        return "full" if val == "full" else "runtime"
    except Exception:
        return "runtime"


def stop_if_running():
    """清理/重启前先停服务：Windows 上日志与行程文件被占用会导致删除跳过。"""
    listen = _listen_map()
    if any(p in listen for p in all_ports()):
        log(f"  {C_YELLOW}[提示]{C_RESET} 检测到服务在运行，先停止以释放文件占用…")
        stop_all()
        time.sleep(1)


def run_reset(scope: str = "runtime", extra_args: list = None) -> int:
    """调用 scripts/reset_data.py 清空运行数据（--yes 免确认，交互确认在调用方做）。"""
    step(f"清空运行数据（scope={scope}）")
    if not RESET_SCRIPT.exists():
        log(f"  {C_RED}[失败]{C_RESET} 未找到清理脚本: {RESET_SCRIPT}")
        return 1
    py = str(VENV_PY) if VENV_PY.exists() else get_python()
    cmd = [py, str(RESET_SCRIPT), "--scope", scope, "--yes"] + list(extra_args or [])
    log(f"  {C_DIM}> {' '.join(cmd)}{C_RESET}")
    try:
        code = subprocess.run(cmd, cwd=str(BASE_DIR)).returncode  # 不捕获，清理明细直接可见
    except Exception as e:
        log(f"  {C_RED}[失败]{C_RESET} {e}")
        return 1
    if code == 0:
        log(f"  {C_GREEN}[OK]{C_RESET} 运行数据已清空（原数据备份在 .backup/，保留最近 3 份）")
    else:
        log(f"  {C_RED}[失败]{C_RESET} 清理脚本退出码 {code}（可先执行停止再重试）")
    return code


def confirm_clean(scope: str = "runtime") -> bool:
    log(f"{C_YELLOW}即将清空：行程记录 / 审批单 / 报销单 / 用户画像 / 日志 / 各类缓存{C_RESET}")
    if scope == "full":
        log(f"{C_YELLOW}额外清空：组织架构 / 员工 / 差旅政策 / 政策文档 / 行程模板{C_RESET}")
    log(f"{C_DIM}原数据先备份到 .backup/（保留最近 3 份）；data/system 后台配置与大模型密钥不受影响。{C_RESET}")
    try:
        return input('确认请输入 yes（其他输入取消）: ').strip().lower() in ("yes", "y")
    except (EOFError, KeyboardInterrupt):
        return False


def fresh_start(mode: str = DEFAULT_MODE):
    """干净启动：停止 → 清空运行数据 → 正常启动（工作台带 ?fresh=1 清对话）。"""
    mode = normalize_mode(mode)
    log(f"{APP_TITLE} —— 干净启动 · {MODE_LABELS.get(mode, mode)}")
    stop_if_running()
    if run_reset("runtime") != 0:
        log(f"{C_YELLOW}[提示]{C_RESET} 清理未完全成功，仍继续启动；可稍后在本菜单重试清空。")
    one_shot_start(mode, enter_menu=False, auto_fresh=False)


# ---------------------------------------------------------------------------
# 统一控制台（交互菜单）
# ---------------------------------------------------------------------------
def interactive_menu(mode: str = DEFAULT_MODE):
    """总控台：状态面板 + 启动/停止/重启/日志/工作台，一个窗口管完。"""
    current = normalize_mode(mode)
    while True:
        actions = (
            f"[1] 启动 · 单体模式（推荐·单进程单端口）   [2] 启动 · 微服务模式（3 端口）\n"
            f"[3] 停止全部（含前端）   [4] 重启当前模式（{MODE_LABELS.get(current, current)}）\n"
            f"[5] 查看服务日志   [6] 打开日志目录   [7] 打开工作台   [8] 刷新状态\n"
            f"[9] 清空运行数据（行程/审批/报销/日志/缓存）   [10] 干净启动（清空后启动）\n"
            f"[11] 每次启动自动清空：{C_GREEN + '已开启' + C_RESET if FRESH_FLAG.exists() else C_DIM + '已关闭' + C_RESET}\n"
            f"[0] 退出（服务继续后台运行）"
        )
        log()
        all_up = status_table(current)
        if all_up:
            log(f"  {C_GREEN}✓ 当前模式服务运行中{C_RESET}  工作台: {APP_URL}")
        log()
        log(actions)
        try:
            choice = input("请选择: ").strip()
        except (EOFError, KeyboardInterrupt):
            log("\n已退出（服务继续后台运行）。")
            return
        if choice in ("1", "2"):
            new_mode = "single" if choice == "1" else "micro"
            if new_mode != current and any(is_port_alive(p) for p in all_ports()):
                log(f"  {C_YELLOW}[提示]{C_RESET} 检测到已有服务在运行，先停止再以新模式启动…")
                stop_all()
                time.sleep(1)
            current = new_mode
            start_all(current)
            wait_for_health(current)
            reset_chat_history(current)
            open_browser(reset_chat=True)
        elif choice == "3":
            stop_all()
        elif choice == "4":
            stop_all()
            time.sleep(1)
            start_all(current)
            wait_for_health(current)
            reset_chat_history(current)
            open_browser(reset_chat=True)
        elif choice == "5":
            names = [log_name for _, _, _, _, log_name in backends_for(current)] + [FRONTEND_LOG]
            disp = [d for _, d, _, _, _ in backends_for(current)] + ["前端工作台"]
            for i, d in enumerate(disp, 1):
                log(f"  [{i}] {d} ({names[i - 1]})")
            try:
                idx = input("查看哪个日志（回车取消）: ").strip()
                if idx.isdigit() and 1 <= int(idx) <= len(names):
                    tail_log(names[int(idx) - 1])
            except (EOFError, KeyboardInterrupt):
                pass
        elif choice == "6":
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if IS_WIN:
                os.startfile(str(LOG_DIR))  # noqa: S606
            else:
                run(["xdg-open", str(LOG_DIR)], check=False)
        elif choice == "7":
            open_browser(reset_chat=True)
        elif choice == "8":
            continue  # 回到循环顶自动刷新状态
        elif choice == "9":
            if confirm_clean("runtime"):
                stop_if_running()
                run_reset("runtime")
            else:
                log("已取消。")
        elif choice == "10":
            fresh_start(current)
        elif choice == "11":
            if FRESH_FLAG.exists():
                try:
                    FRESH_FLAG.unlink()
                except Exception as e:
                    log(f"  {C_RED}[失败]{C_RESET} 关闭失败: {e}")
                else:
                    log(f"  {C_GREEN}[OK]{C_RESET} 已关闭：以后启动不再自动清空（历史数据保留）。")
            else:
                try:
                    FRESH_FLAG.write_text("runtime", encoding="utf-8")
                except Exception as e:
                    log(f"  {C_RED}[失败]{C_RESET} 开启失败: {e}")
                else:
                    log(f"  {C_GREEN}[OK]{C_RESET} 已开启：以后每次启动（start.bat / 本菜单）都会先清空上次的行程与缓存。")
                    log(f"  {C_DIM}想连组织/政策种子一起清，可执行：python scripts/reset_data.py --scope full --reseed{C_RESET}")
        elif choice == "0":
            log("已退出（服务继续后台运行；停止请双击 停止.bat 或 python launcher.py stop）。")
            return


def one_shot_start(mode: str = DEFAULT_MODE, enter_menu: bool = False,
                   auto_fresh: bool = True, reset_chat: bool = True):
    """完整一键链路：环境 → 依赖 → 并行启动 → 健康检查 → 开页面。

    默认单体模式（单进程单端口 8001）；默认不驻留窗口（enter_menu=False），
    双击 start.bat 的窗口启动完自动关闭，重复双击不会叠出一堆黑窗。
    常驻控制台用命令行 `python launcher.py menu`。
    auto_fresh=True 且存在 .cjh_fresh 标记时，启动前自动清空上次运行数据。
    reset_chat=True（默认）时工作台以 ?fresh=1 打开，**只清对话记录**
    （前端快照 + 服务端会话历史），行程等业务数据一律保留。
    """
    mode = normalize_mode(mode)
    log(f"{APP_TITLE} —— 一键启动 · {MODE_LABELS.get(mode, mode)}")
    try:
        if auto_fresh and FRESH_FLAG.exists():
            log()
            log(f"{C_YELLOW}[自动清空]{C_RESET} 已开启「每次启动自动清空」，先清理上一次的运行数据…")
            stop_if_running()
            run_reset(_fresh_scope())

        step("1/环境检查")
        check_python()

        step("2/依赖检查（增量）")
        ensure_venv()
        ensure_frontend()

        backends = backends_for(mode)
        backends_up = all(is_port_alive(b[3]) for b in backends)
        if backends_up and is_port_alive(FRONTEND_PORT, path="/"):
            log()
            log(f"{C_GREEN}[OK]{C_RESET} 全套服务已在运行，无需启动。")
            if reset_chat:
                reset_chat_history(mode)
            open_browser(reset_chat)
        else:
            start_all(mode)
            wait_for_health(mode)
            if reset_chat:
                reset_chat_history(mode)
            open_browser(reset_chat)

        log()
        log(f"  工作台: {APP_URL}")
        log(f"  {C_DIM}停止服务：双击 停止.bat{C_RESET}")

        if enter_menu:
            interactive_menu(mode)
        else:
            log()
            log(f"{C_GREEN}[OK]{C_RESET} 服务已在后台运行；本窗口可关闭，不影响服务。")
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
# CLI 入口：start / menu / stop / restart / status / clean / fresh（可带模式 single|micro）
# ---------------------------------------------------------------------------
def cli():
    raw = [a.strip() for a in sys.argv[1:] if a.strip()]
    # 先摘掉开关型参数，避免它们被误当成 action / mode
    keep_chat = any(a.lower() in ("--keep-chat", "keep-chat") for a in raw)
    reset_chat = not keep_chat
    args = [a for a in raw if a.lower() not in ("--keep-chat", "keep-chat")]

    action = args[0].lower() if args else "start"
    # 模式可能出现在第 2 位（start micro），或独占第 1 位（micro）
    mode_arg = args[1] if len(args) > 1 else (args[0] if args and args[0].lower() in MODE_ALIASES else None)
    mode = normalize_mode(mode_arg)

    if action == "stop":
        stop_all()
        _pause_if_tty()
    elif action == "restart":
        stop_all()
        time.sleep(1)
        one_shot_start(mode, enter_menu=False, reset_chat=reset_chat)
        _pause_if_tty()
    elif action == "status":
        all_up = status_table(mode)
        log()
        log(f"工作台: {APP_URL}")
        _pause_if_tty()
        sys.exit(0 if all_up else 1)
    elif action in ("menu", "console"):
        one_shot_start(mode, enter_menu=True, reset_chat=reset_chat)
    elif action in ("clean", "reset"):
        scope = "full" if any(a in ("--full", "full") for a in args[1:]) else "runtime"
        passthrough = [a for a in args[1:] if a in ("--dry-run", "--no-backup", "--reseed")]
        stop_if_running()
        if confirm_clean(scope):
            run_reset(scope, passthrough)
            if scope == "full":
                log(f"  {C_DIM}提示：组织/政策种子已一并清空，可执行 python scripts/reset_data.py --scope full --reseed 重新灌种子。{C_RESET}")
        else:
            log("已取消。")
        _pause_if_tty()
    elif action == "fresh":
        fresh_start(mode)
        _pause_if_tty()
    elif action in MODE_ALIASES:
        # 只给了模式（如 launcher.py micro）：按该模式启动
        one_shot_start(mode, enter_menu=False, reset_chat=reset_chat)
    else:  # start —— 默认启动完即收窗（不叠窗；失败才会停留显示报错）
        one_shot_start(mode, enter_menu=False, reset_chat=reset_chat)


if __name__ == "__main__":
    cli()
