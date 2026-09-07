# -*- coding: utf-8 -*-
"""前台运行单个后端服务（供 AI 会话的后台任务使用）。

与 scripts/start_local.py 的环境注入逻辑保持一致，但不 detach——
进程前台阻塞运行，由外部（后台任务）托管生命周期。
用已被占用端口自检跳过：若目标端口已被本服务占用则直接退出。

用法:
    python scripts/fg_service.py journey   # 8001
    python scripts/fg_service.py planner   # 8002
    python scripts/fg_service.py sense     # 8003
"""
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SERVICES = {
    "journey": ("services/journey-hub", 8001),
    "planner": ("services/planner-core", 8002),
    "sense":   ("services/sense-engine", 8003),
}


def load_env_file() -> dict:
    env = {}
    env_path = ROOT / ".env"
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


def port_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "journey"
    service_dir, port = SERVICES[name]
    workdir = str(ROOT / service_dir)

    if port_alive(port):
        print(f"[fg_service] :{port} 已有服务在运行，跳过启动", flush=True)
        return

    env = os.environ.copy()
    env.update(load_env_file())
    env["PYTHONPATH"] = f"{ROOT};{workdir}"
    env["PLANNER_SERVICE_URL"] = "http://127.0.0.1:8002"
    env["SENSE_SERVICE_URL"] = "http://127.0.0.1:8003"
    env.setdefault("DEV_API_KEY", "ak_dev_local")

    # 关键：必须写回 os.environ——settings 在 import api.main 时才读 os.getenv
    os.environ.clear()
    os.environ.update(env)

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, workdir)
    os.chdir(workdir)

    import uvicorn
    from api.main import app

    print(f"[fg_service] {name} 启动 :{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None)


if __name__ == "__main__":
    main()
