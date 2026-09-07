"""
AI出行管家 本地一键启动脚本（无需 Docker）

用法:
    python scripts/start_local.py          # 启动全部 3 个服务（后台 detach）
    python scripts/start_local.py --only journey    # 只启动行智
    python scripts/start_local.py --check   # 检查依赖
    python scripts/stop_local.py            # 停止全部服务
"""
import os
import sys
import time
import subprocess
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SERVICES = {
    "journey":  ("行智 · Journey Hub",   "services/journey-hub",  8001),
    "planner":  ("策程 · Planner Core",  "services/planner-core", 8002),
    "sense":    ("感知 · Sense Engine",  "services/sense-engine", 8003),
}

PID_DIR = ROOT / ".run"
LOG_DIR = ROOT / ".logs"

if sys.platform == "win32":
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000
    DETACH_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
else:
    DETACH_FLAGS = 0


def get_venv_python() -> str:
    """优先使用项目虚拟环境解释器，保证依赖与 launcher 一致。"""
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def build_command(service_dir: str, port: int) -> list:
    # 显式 --app-dir，避免依赖 cwd/PYTHONPATH 解析 api.main 模块
    return [
        get_venv_python(), "-m", "uvicorn",
        "api.main:app",
        "--app-dir", str(ROOT / service_dir),
        "--host", "127.0.0.1",
        "--port", str(port),
    ]


def check_dependencies() -> list:
    required = [
        "fastapi", "uvicorn", "langgraph", "apscheduler",
        "requests", "prometheus_client",
    ]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    return missing


def load_env_file() -> dict:
    env_path = ROOT / ".env"
    env = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and not value.startswith("sk-your"):
            env[key] = value
    return env


def write_pid(name: str, pid: int):
    PID_DIR.mkdir(parents=True, exist_ok=True)
    (PID_DIR / f"{name}.pid").write_text(str(pid))


def start_service(name: str) -> subprocess.Popen:
    """启动单个服务（detach 模式）"""
    label, service_dir, port = SERVICES[name]
    workdir = ROOT / service_dir

    env = os.environ.copy()
    env.update(load_env_file())
    env["PYTHONPATH"] = f"{ROOT};{workdir}" + (
        f";{env['PYTHONPATH']}" if env.get("PYTHONPATH") else ""
    )
    env["PLANNER_SERVICE_URL"] = "http://127.0.0.1:8002"
    env["SENSE_SERVICE_URL"] = "http://127.0.0.1:8003"
    env.setdefault("DEV_API_KEY", "ak_dev_local")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(LOG_DIR / f"{name}.log", "ab")

    proc = subprocess.Popen(
        build_command(service_dir, port),
        cwd=workdir,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=DETACH_FLAGS if sys.platform == "win32" else 0,
        close_fds=True,
    )

    write_pid(name, proc.pid)
    print(f"  [启动] {label} (:{port}) PID={proc.pid}")
    return proc


def is_port_alive(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def kill_port(port: int) -> list:
    """按端口杀掉占用进程，返回被杀的 PID 列表。"""
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout or ""
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, state, pid = parts[1], parts[3].upper(), parts[4]
        if state != "LISTENING" or not local.endswith(f":{port}"):
            continue
        if not pid.isdigit() or int(pid) == 0 or pid in pids:
            continue
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
        pids.append(pid)
    return pids


def kill_existing(names: list):
    """杀掉指定服务的已有进程（按端口为主，PID 文件兜底）"""
    if sys.platform != "win32":
        return
    for name in names:
        pids = kill_port(SERVICES[name][2])
        if pids:
            print(f"  [清理端口] {name} :{SERVICES[name][2]} PID={', '.join(pids)}")
        pid_file = PID_DIR / f"{name}.pid"
        if not pid_file.exists():
            continue
        try:
            pid = int(pid_file.read_text().strip())
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        except Exception:
            pass
        try:
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description="AI出行管家 本地启动（后台模式）")
    parser.add_argument("--only", choices=list(SERVICES.keys()), help="只启动指定服务")
    parser.add_argument("--check", action="store_true", help="只检查依赖")
    args = parser.parse_args()

    print("=" * 60)
    print("AI出行管家 · 本地启动")
    print("=" * 60)

    missing = check_dependencies()
    if missing:
        print(f"\n[错误] 缺少依赖: {', '.join(missing)}")
        print("请先安装: pip install -r requirements.txt")
        sys.exit(1)
    print("\n[OK] 依赖完整")

    if args.check:
        return

    to_start = [args.only] if args.only else list(SERVICES.keys())
    kill_existing(to_start)
    # 等端口真正释放，否则新进程会撞上 TIME_WAIT/占用导致启动失败
    time.sleep(2)

    print(f"\n[启动] {len(to_start)} 个服务（后台模式）")
    for name in to_start:
        start_service(name)

    print("\n[健康检查] 等待服务就绪...")
    time.sleep(4)
    print("\n" + "=" * 60)
    print("服务状态:")
    for name in to_start:
        label, _, port = SERVICES[name]
        alive = is_port_alive(port)
        status = "[OK] 运行中" if alive else "[FAIL] 启动失败（查看日志）"
        print(f"  [{name}] {label} :{port} {status}")

    print("\n" + "=" * 60)
    print("Swagger 文档:")
    for name in to_start:
        _, _, port = SERVICES[name]
        print(f"  http://localhost:{port}/docs")
    print(f"\n日志位置: {LOG_DIR}")
    print("停止全部: python scripts/stop_local.py")
    sys.exit(0)


if __name__ == "__main__":
    main()
