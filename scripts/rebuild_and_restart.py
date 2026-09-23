# -*- coding: utf-8 -*-
"""
一键全面更新 —— 停止服务 → 重新打包 EXE → 重启服务 → 验证

解决的问题：
  1. 旧服务进程一直不重启，导致代码修复（中文乱码补丁）不生效
  2. .run/*.pid 过期，stop_local.py 按 PID 杀进程杀不掉
  3. EXE 内打包的是旧 launcher，需要重新构建

打包产物布局：spec / build / dist 全部落在 .build/（每次打包前整体清空），
根目录只保留最终启动器 CorporateJourneyHub.exe，不再散落小文件。

用法（双击或命令行均可）:
    python scripts/rebuild_and_restart.py            # 完整流程（停止+打包+启动+验证）
    python scripts/rebuild_and_restart.py --no-build # 跳过打包，只重启并验证
"""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "CorporateJourneyHub.exe"

SERVICES = {
    "journey": ("行智 · Journey Hub", 8001),
    "planner": ("策程 · Planner Core", 8002),
    "sense": ("感知 · Sense Engine", 8003),
}


def log(msg=""):
    print(msg, flush=True)


def step(title):
    log("")
    log("=" * 60)
    log(title)
    log("=" * 60)


def venv_python() -> str:
    p = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(p) if p.exists() else sys.executable


def run(cmd, **kw):
    log(f"  > {' '.join(str(c) for c in cmd)}")
    return subprocess.run([str(c) for c in cmd], cwd=str(ROOT), **kw)


def listening_pids(port: int) -> list:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout or ""
    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "LISTENING" or not parts[1].endswith(f":{port}"):
            continue
        pid = parts[4]
        if pid.isdigit() and pid != "0" and pid not in pids:
            pids.append(pid)
    return pids


def stop_services():
    step("1/停止现有服务（按端口精准清理）")
    for name, (label, port) in SERVICES.items():
        pids = listening_pids(port)
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
        log(f"  [{'停止' if pids else '空闲'}] {label} :{port} {pids if pids else ''}")
    # 清掉过期 PID 文件
    for name in SERVICES:
        (ROOT / ".run" / f"{name}.pid").unlink(missing_ok=True)
    time.sleep(2)
    log("  [OK] 服务已全部停止")


def build_exe():
    step("2/重新打包 EXE（中间产物收进 .build/）")
    script = ROOT / "scripts" / "build_exe.py"
    if not script.exists():
        log("  [跳过] 未找到 scripts/build_exe.py")
        return
    # 不捕获输出：PyInstaller 日志直接流到本控制台，失败原因一眼可见
    r = run([venv_python(), script])
    if r.returncode == 0 and EXE.exists():
        log(f"  [OK] 打包完成: {EXE.name}")
    else:
        log(f"  [警告] 打包失败（退出码 {r.returncode}），详见上方 PyInstaller 输出")
        log("  不影响服务运行（EXE 只是启动器），继续启动服务。")


def start_services():
    step("3/启动服务（加载已修复的代码）")
    r = run([venv_python(), "scripts/start_local.py"], capture_output=True, text=True)
    log(r.stdout or "")
    if r.returncode != 0:
        log(f"[启动输出-错误]\n{r.stderr or ''}")
    return r.returncode


def verify():
    step("4/健康检查")
    ok = True
    deadline = time.time() + 60
    while time.time() < deadline:
        states = {n: bool(alive(p)) for n, (_, p) in SERVICES.items()}
        if all(states.values()):
            break
        time.sleep(2)
    for name, (label, port) in SERVICES.items():
        up = alive(port)
        log(f"  [{'OK' if up else 'FAIL'}] {label} :{port}")
        ok = ok and up
    return ok


def alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    log("企业智行 · 全面更新（停止 → 打包 → 启动 → 验证）")
    try:
        stop_services()
        if "--no-build" not in sys.argv:
            build_exe()
        else:
            log("\n[跳过打包] --no-build")
        start_services()
        ok = verify()
        step("结果")
        if ok:
            log("全部服务已用最新代码启动。")
            log("请在页面重新生成一条行程，确认中文显示正常。")
        else:
            log("部分服务未就绪，请查看日志目录: .logs/")
    except Exception as e:
        log(f"\n[执行失败] {e}")
    if sys.stdin and sys.stdin.isatty():
        input("\n按 Enter 退出。")


if __name__ == "__main__":
    main()
