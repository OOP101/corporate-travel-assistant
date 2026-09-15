# -*- coding: utf-8 -*-
"""
企业智行 · 运行数据清空（干净启动 / 重置演示环境）

用法（项目根目录，建议先停止服务）:
    python scripts/reset_data.py                         # 清运行态数据（默认，需输入 yes 确认）
    python scripts/reset_data.py --yes                   # 免确认（launcher/menu 调用）
    python scripts/reset_data.py --scope full            # 连组织/政策种子一起清（真·全清）
    python scripts/reset_data.py --scope full --reseed   # 清完自动重灌 P1 种子数据
    python scripts/reset_data.py --no-backup             # 不备份直接删（谨慎）
    python scripts/reset_data.py --dry-run               # 只列出将要清理的内容，不动手

清理范围（scope=runtime，默认）:
    行程记录    data/trips/            data/test_trips/
    业务单据    data/org/approvals/    data/org/reimbursements/
    用户画像    data/profiles/
    运行状态    .logs/                .run/
    各类缓存    __pycache__ / .pytest_cache / .pytest_tmp / frontend/node_modules/.vite / frontend/dist

清理范围（scope=full，额外）:
    组织与语料种子  data/org/{departments,employees,policies,policy_docs,guide_docs}
    行程模板        data/templates/

永不清理:
    data/system/    后台配置（大模型 provider / 管理员账号）—— 清了要重新配
    .env  .venv/  frontend/node_modules/（主体）  项目源码

安全约定:
  - 默认先把要删的东西整体搬到 .backup/reset-<时间戳>/（可回滚），保留最近 3 份；
  - 只允许操作 BASE_DIR 之内、且不等于 BASE_DIR 的路径，越界直接拒绝；
  - 单个目标被占用（服务没停）时跳过并提示，不中断其余清理。
"""
import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_ROOT = BASE_DIR / ".backup"
KEEP_BACKUPS = 3

# 整目录清理（含目录本身；keep=True 表示清完后重建空目录）
RUNTIME_TREES = [
    (".logs", True),
    (".run", True),
    (".pytest_cache", False),
    (".pytest_tmp", False),
    ("frontend/dist", False),
    ("frontend/node_modules/.vite", False),
]
# 只清目录内容（目录保留）
RUNTIME_CONTENTS = [
    "data/trips",              # 行程记录（正式）
    "data/test_trips",         # 行程记录（测试）
    "data/org/approvals",      # 审批单
    "data/org/reimbursements", # 报销单
    "data/profiles",           # 用户画像缓存
]
# scope=full 时额外清理
FULL_CONTENTS_EXTRA = [
    "data/org/departments",
    "data/org/employees",
    "data/org/policies",
    "data/org/policy_docs",
    "data/org/guide_docs",   # 景点/攻略语料（种子）
    "data/templates",
]
# 递归查找的缓存目录名（跳过虚拟环境与 node_modules 主体）
CACHE_DIR_NAMES = {"__pycache__"}
CACHE_SKIP_PARTS = {".venv", "venv", "node_modules", ".git", ".backup", ".workbuddy"}


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(BASE_DIR.resolve())).replace("\\", "/")
    except Exception:
        return str(p)


def _guard(p: Path) -> Path:
    """拒绝 BASE_DIR 之外或 BASE_DIR 本身的路径。"""
    rp = Path(p).resolve()
    base = BASE_DIR.resolve()
    if rp == base or base not in rp.parents:
        raise SystemExit(f"[拒绝] 路径越界，已中止: {rp}")
    return rp


def _on_rm_error(func, path, exc_info):
    """只读文件兜底：去掉只读位后重试删除。"""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        raise


CATEGORIES = [
    ("data/trips/", "行程记录（正式）"),
    ("data/test_trips/", "行程记录（测试）"),
    ("data/org/approvals/", "审批单"),
    ("data/org/reimbursements/", "报销单"),
    ("data/org/departments/", "组织架构（种子）"),
    ("data/org/employees/", "员工（种子）"),
    ("data/org/policies/", "差旅政策（种子）"),
    ("data/org/policy_docs/", "政策文档（种子）"),
    ("data/org/guide_docs/", "景点/攻略语料（种子）"),
    ("data/profiles/", "用户画像"),
    ("data/templates/", "行程模板"),
    (".logs", "运行日志"),
    (".run", "PID/运行状态"),
    ("frontend/dist", "前端构建产物"),
    ("frontend/node_modules/.vite", "Vite 预构建缓存"),
    (".pytest_cache", "测试缓存"),
    (".pytest_tmp", "测试临时目录"),
    ("__pycache__", "Python 字节码缓存"),
]


def _category(rel: str) -> str:
    for prefix, name in CATEGORIES:
        if prefix in rel or rel == prefix:
            return name
    return "其他"


class Cleaner:
    def __init__(self, scope: str = "runtime", backup: bool = True, dry_run: bool = False):
        self.scope = scope
        self.backup = backup
        self.dry_run = dry_run
        self.items = []          # (src: Path, keep_dir: bool)
        self.skipped = []        # (rel, reason)
        self.count = 0
        self.backup_dir = None
        self.stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # -- 采集 ---------------------------------------------------------------
    def collect(self):
        for rel, keep in RUNTIME_TREES:
            p = BASE_DIR / rel
            if p.exists():
                self.items.append((_guard(p), keep))
        for rel in RUNTIME_CONTENTS + (FULL_CONTENTS_EXTRA if self.scope == "full" else []):
            p = BASE_DIR / rel
            if not p.exists():
                continue
            _guard(p)
            children = sorted(p.iterdir(), key=lambda x: x.name)
            for c in children:
                self.items.append((_guard(c), False))
            if not children:
                self.items.append((p, True))  # 空目录也登记一下，便于报告
        for d in self._cache_dirs():
            self.items.append((d, False))

    def _cache_dirs(self):
        found = []
        for root, dirs, _ in os.walk(BASE_DIR):
            parts = set(Path(root).relative_to(BASE_DIR).parts)
            if parts & CACHE_SKIP_PARTS:
                dirs[:] = [d for d in dirs if d in CACHE_SKIP_PARTS]
                continue
            dirs[:] = [d for d in dirs if d not in CACHE_SKIP_PARTS]
            for d in list(dirs):
                if d in CACHE_DIR_NAMES:
                    found.append(_guard(Path(root) / d))
        return found

    # -- 执行 ---------------------------------------------------------------
    def run(self) -> dict:
        self.collect()
        if self.dry_run:
            return self._summary()

        if self.backup and self.items:
            self.backup_dir = BACKUP_ROOT / f"reset-{self.stamp}"
            self.backup_dir.mkdir(parents=True, exist_ok=True)

        for src, keep in self.items:
            try:
                if self.backup:
                    dest = self.backup_dir / _rel(src)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists():
                        shutil.rmtree(dest, onerror=_on_rm_error) if dest.is_dir() else dest.unlink()
                    shutil.move(str(src), str(dest))
                elif src.is_dir():
                    shutil.rmtree(src, onerror=_on_rm_error)
                else:
                    os.chmod(src, stat.S_IWRITE)
                    src.unlink()
                self.count += 1
                if keep:
                    src.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.skipped.append((_rel(src), f"{type(e).__name__}: {e}"))

        if self.backup_dir and not any(self.backup_dir.iterdir()):
            try:
                self.backup_dir.rmdir()
                self.backup_dir = None
            except Exception:
                pass
        self._prune_backups()
        return self._summary()

    def _prune_backups(self):
        if not BACKUP_ROOT.exists():
            return
        # 只裁自己产生的 reset-* 目录，别动 .backup/ 下其他用途的备份（如 root-cleanup-*）
        dirs = sorted([d for d in BACKUP_ROOT.iterdir()
                       if d.is_dir() and d.name.startswith("reset-")],
                      key=lambda d: d.stat().st_mtime, reverse=True)
        for old in dirs[KEEP_BACKUPS:]:
            shutil.rmtree(old, ignore_errors=True)

    def _summary(self) -> dict:
        return {
            "scope": self.scope,
            "dry_run": self.dry_run,
            "planned": len(self.items),
            "cleared": self.count,
            "skipped": [{"path": p, "reason": r} for p, r in self.skipped],
            "backup_dir": str(self.backup_dir) if self.backup_dir else "",
        }

    def report(self):
        head = "将要清理" if self.dry_run else "已清理"
        # 按类别汇总，避免几百条行程糊屏；同类只列前 3 条样例
        groups = {}
        for src, keep in self.items:
            groups.setdefault(_category(_rel(src)), []).append((_rel(src), keep))
        print(f"\n{head} {len(self.items)} 项（scope={self.scope}）：")
        for name, rows in groups.items():
            print(f"  · {name}：{len(rows)} 项")
            for rel, keep in rows[:3]:
                print(f"      - {rel}{'（保留空目录）' if keep else ''}")
            if len(rows) > 3:
                print(f"      ... 其余 {len(rows) - 3} 项同类省略")
        if self.backup_dir:
            print(f"\n原数据已备份到：{_rel(self.backup_dir)}（可回滚，仅保留最近 {KEEP_BACKUPS} 份）")
        if self.skipped:
            print(f"\n[跳过] {len(self.skipped)} 项（多为服务未停止导致文件被占用）：")
            for p, r in self.skipped[:15]:
                print(f"  - {p}  ←  {r}")
            print("  提示：先执行 停止.bat 或 python launcher.py stop，再重试清理。")
        if not self.dry_run:
            print(f"\n完成：共清理 {self.count} 项，跳过 {len(self.skipped)} 项。")


def confirm(scope: str) -> bool:
    print("=" * 60)
    print("企业智行 · 运行数据清空" + ("（scope=full 真·全清，含组织/政策种子）" if scope == "full" else ""))
    print("=" * 60)
    print("将清空：行程记录 / 审批单 / 报销单 / 用户画像 / 日志 / 各类缓存")
    if scope == "full":
        print("额外清空：组织架构 / 员工 / 差旅政策 / 政策文档 / 行程模板")
        print("（data/system 后台配置与大模型密钥不受影响）")
    print("默认先备份到 .backup/ 再删除，可回滚。")
    try:
        return input('\n确认请输入 yes（其他任意输入取消）: ').strip().lower() in ("yes", "y")
    except (EOFError, KeyboardInterrupt):
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="企业智行 · 运行数据清空")
    ap.add_argument("--scope", choices=["runtime", "full"], default="runtime",
                    help="runtime=仅运行态数据（默认）；full=连组织/政策种子一起清")
    ap.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    ap.add_argument("--no-backup", action="store_true", help="不备份，直接删除")
    ap.add_argument("--dry-run", action="store_true", help="只列出将清理的内容")
    ap.add_argument("--reseed", action="store_true", help="清空后重新灌入 P1 种子数据")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果摘要")
    args = ap.parse_args(argv)

    if not args.yes and not args.dry_run and not confirm(args.scope):
        print("已取消，未做任何改动。")
        return 0

    t0 = time.time()
    cleaner = Cleaner(scope=args.scope, backup=not args.no_backup, dry_run=args.dry_run)
    summary = cleaner.run()
    if not args.json:
        cleaner.report()

    if args.reseed and not args.dry_run:
        seed = BASE_DIR / "scripts" / "seed_p1_data.py"
        if seed.exists():
            print("\n重新灌入 P1 种子数据（组织 / 政策 / 政策文档）…")
            code = subprocess.run([sys.executable, str(seed)], cwd=str(BASE_DIR)).returncode
            summary["reseed"] = "ok" if code == 0 else f"failed({code})"
            print("种子数据完成。" if code == 0 else "[警告] 种子数据脚本返回非 0，请查看上方输出。")
        else:
            summary["reseed"] = "seed_p1_data.py not found"

    summary["elapsed"] = round(time.time() - t0, 2)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(f"\n耗时 {summary['elapsed']}s。如服务在运行，请重启后再验证（重启会重新加载内存态）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
