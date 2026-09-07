# -*- coding: utf-8 -*-
"""一次性修复脚本：还原 data/trips/*.json 中被错误解码的中文乱码。

背景: requests 在 LLM 响应头缺少 charset 时会按 ISO-8859-1 解码，
导致 "深圳" 变成 "æ·±å³" 并写入 JSON 文件。本脚本把这些乱码还原。

用法: python scripts/fix_mojibake.py
"""
import json
from pathlib import Path

TRIPS_DIR = Path(__file__).resolve().parent.parent / "services" / "planner-core" / "data" / "trips"


def fix_string(s: str) -> str:
    """尝试把 mojibake 字符串还原为正常 UTF-8 中文。"""
    if not s:
        return s
    try:
        raw = s.encode("latin-1")
    except UnicodeEncodeError:
        # 字符串里含有 latin-1 无法表示的字符（正常中文），说明不是乱码
        return s
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        # 不是 mojibake，保留原文
        return s
    # 还原成功且确实含中文才替换（乱码原本都是中文）
    if any("\u4e00" <= ch <= "\u9fff" for ch in decoded):
        return decoded
    return s


def fix_value(v):
    if isinstance(v, str):
        return fix_string(v)
    if isinstance(v, list):
        return [fix_value(i) for i in v]
    if isinstance(v, dict):
        return {k: fix_value(val) for k, val in v.items()}
    return v


def main():
    files = sorted(TRIPS_DIR.glob("*.json"))
    if not files:
        print(f"未找到行程数据文件: {TRIPS_DIR}")
        return
    changed = 0
    for fp in files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"跳过（无法解析）: {fp.name} -> {e}")
            continue
        fixed = fix_value(data)
        if fixed != data:
            fp.write_text(
                json.dumps(fixed, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            changed += 1
            print(f"已修复: {fp.name}")
    print(f"完成，共修复 {changed} 个文件。")
    if not changed:
        print("没有发现需要修复的乱码文件。")


if __name__ == "__main__":
    main()
