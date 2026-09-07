"""
停止 AI出行管家 全部本地服务

策略（双保险）：
  1. 按端口杀进程 —— 端口是服务的唯一可靠标识，PID 文件可能过期/丢失
  2. 按 PID 文件杀 —— 兜底清理已记录但端口未监听的残留进程
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PID_DIR = ROOT / ".run"

# 服务名 → 端口（与 start_local.py 保持一致）
SERVICES = {
    "journey": 8001,
    "planner": 8002,
    "sense": 8003,
}


def _run(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def kill_by_port(port: int) -> list:
    """按监听端口找到并杀掉进程，返回被杀的 PID 列表。"""
    if sys.platform != "win32":
        return []
    out = _run(["netstat", "-ano"]).stdout or ""
    pids = []
    for line in out.splitlines():
        parts = line.split()
        # TCP  127.0.0.1:8002  0.0.0.0:0  LISTENING  12064
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, state, pid = parts[1], parts[3].upper(), parts[4]
        if state != "LISTENING" or not local.endswith(f":{port}"):
            continue
        if not pid.isdigit() or int(pid) == 0:
            continue
        if pid in pids:
            continue
        _run(["taskkill", "/F", "/PID", pid])
        pids.append(pid)
    return pids


def kill_by_pidfile(name: str) -> list:
    """按 PID 文件清理残留进程。"""
    pid_file = PID_DIR / f"{name}.pid"
    if not pid_file.exists():
        return []
    try:
        pid = int(pid_file.read_text().strip())
        _run(["taskkill", "/F", "/PID", str(pid)])
        killed = [str(pid)]
    except Exception as e:
        print(f"    [跳过] PID 文件解析失败: {e}")
        killed = []
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass
    return killed


def main():
    print("=" * 60)
    print("停止 AI出行管家 全部服务")
    print("=" * 60)

    import time
    stopped = 0
    for name, port in SERVICES.items():
        pids = kill_by_port(port)
        if pids:
            print(f"  [停止] {name} :{port}  PID={', '.join(pids)}")
            stopped += 1
        extra = kill_by_pidfile(name)
        if extra:
            print(f"  [清理] {name} 残留 PID={', '.join(extra)}")

    # 等端口真正释放，避免立刻重启时报端口占用
    if stopped:
        time.sleep(2)

    if stopped == 0:
        print("  没有正在运行的服务。")
    else:
        print(f"\n已停止 {stopped} 个服务。")


if __name__ == "__main__":
    main()
