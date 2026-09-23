# -*- coding: utf-8 -*-
"""
一键打包 EXE —— 中间产物全部收进 .build/，根目录不再散落小文件

旧做法的问题：
  PyInstaller 默认把 spec / build/ / dist/ 写在当前目录（即项目根），
  每次打包根目录就多出 CorporateJourneyHub.spec + build/ + dist/ 一堆文件，
  反复打包后根目录越来越乱。

现在的布局：
  .build/                       每次打包前清空，只留最近一次
    ├── CorporateJourneyHub.spec
    ├── build/                  PyInstaller 工作目录（临时文件都在这里）
    └── dist/                   CorporateJourneyHub.exe（中间产物）
  根目录只保留最终产物 CorporateJourneyHub.exe（启动器，删掉就没法双击启动）。

用法：
    python scripts/build_exe.py            # 打包
    python scripts/build_exe.py --no-pip   # 跳过 pip 安装检查
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / ".build"          # 所有中间产物的唯一落点
ENTRY = ROOT / "launcher.py"
APP_NAME = "CorporateJourneyHub"
FINAL_EXE = ROOT / f"{APP_NAME}.exe"

# 历史遗留：旧脚本直接写在根目录的产物
LEGACY = ("build", "dist", f"{APP_NAME}.spec")


def log(msg=""):
    print(msg, flush=True)


def step(title):
    log("")
    log("=" * 60)
    log(title)
    log("=" * 60)


def _pyinstaller_version(exe: str):
    """该解释器装了 PyInstaller 就返回版本号，否则 None。"""
    try:
        r = subprocess.run(
            [exe, "-c", "import PyInstaller; print(PyInstaller.__version__)"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def pick_python():
    """挑一个已经装了 PyInstaller 的解释器。

    本机实况：PyInstaller 装在 D:\\software\\Python311（走 py 启动器），
    项目 .venv 与 PATH 上的 python 都没有 —— 旧脚本写死 python，
    每次都要重装一遍，装不上就直接失败。所以这里按顺序探测，装在哪就用哪：
        项目 .venv → py 启动器 → PATH python → 当前解释器
    """
    cands = []
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        cands.append(str(venv))
    for name in ("py", "python"):
        found = shutil.which(name)
        if found:
            cands.append(found)
    cands.append(sys.executable)

    uniq = list(dict.fromkeys(cands))
    for exe in uniq:
        ver = _pyinstaller_version(exe)
        if ver:
            return exe, ver
    return (uniq[0] if uniq else sys.executable), None


def install_pyinstaller(py: str) -> bool:
    log(f"  [安装] {Path(py).name} 环境下未检测到 PyInstaller，正在安装...")
    r = subprocess.run([py, "-m", "pip", "install", "pyinstaller"], cwd=str(ROOT))
    if r.returncode != 0:
        log("  [失败] 安装失败（检查网络，或改用 py 启动器所在环境）")
        return False
    log("  [OK] 安装完成")
    return True


def clean_build_dir():
    step("1/准备 .build 工作目录")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
        log(f"  [清理] 已清空 {BUILD_DIR.name}/")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy():
    """把旧版遗留在根目录的 spec/build/dist 清掉，避免和新布局并存。"""
    removed = []
    for name in LEGACY:
        p = ROOT / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            removed.append(f"{name}/")
        elif p.exists():
            p.unlink()
            removed.append(name)
    if removed:
        log(f"  [迁移] 清理根目录旧产物: {', '.join(removed)}")


def run_pyinstaller(py: str) -> int:
    step("3/打包 EXE（中间产物写入 .build/）")
    if not ENTRY.exists():
        log(f"  [失败] 找不到入口文件 {ENTRY.name}")
        return 1
    cmd = [
        py, "-m", "PyInstaller",
        "--onefile", "--console", "--clean", "--noconfirm",
        "--name", APP_NAME,
        "--specpath", str(BUILD_DIR),
        "--workpath", str(BUILD_DIR / "build"),
        "--distpath", str(BUILD_DIR / "dist"),
        str(ENTRY),
    ]
    log(f"  > {APP_NAME}.exe  ←  {ENTRY.name}")
    r = subprocess.run(cmd, cwd=str(ROOT))
    return r.returncode


def publish() -> bool:
    step("4/取出启动器")
    built = BUILD_DIR / "dist" / f"{APP_NAME}.exe"
    if not built.exists():
        log(f"  [失败] 未生成 {built.relative_to(ROOT)}")
        return False
    size_mb = built.stat().st_size / 1024 / 1024
    shutil.copyfile(built, FINAL_EXE)
    log(f"  [OK] {FINAL_EXE.name}  ({size_mb:.1f} MB) 已放到项目根目录")
    log(f"  中间产物保留在 {BUILD_DIR.name}/（spec / build / dist），下次打包会整体清空")
    return True


def main():
    t0 = time.time()
    log("企业智行 · 打包启动器 EXE")
    clean_build_dir()
    migrate_legacy()

    step("2/选择 Python 环境")
    py, ver = pick_python()
    log(f"  [环境] {py}")
    if ver:
        log(f"  [OK] 已装 PyInstaller {ver}")
    elif "--no-pip" in sys.argv:
        log("  [跳过] 未装 PyInstaller，且已指定 --no-pip")
        log("         请先执行: py -m pip install pyinstaller")
        return 1
    elif not install_pyinstaller(py):
        return 1

    rc = run_pyinstaller(py)
    if rc != 0:
        log("")
        log(f"[失败] PyInstaller 退出码 {rc}，日志见上方输出")
        log(f"       工作目录 {BUILD_DIR.name}/ 已保留，便于排查")
        return 1

    if not publish():
        return 1

    step("完成")
    log(f"耗时 {time.time() - t0:.1f}s · 根目录只多了 {FINAL_EXE.name} 一个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
