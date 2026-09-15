"""大模型 JSON 输出容错解析 —— shared 公共层

背景：让大模型直接吐多日行程这种**嵌套深、体积大**的 JSON，高频出现两类故障：

1. **被 max_tokens 截断** —— 尾部少一个 `]` 或 `}`，甚至停在一个没写完的字符串中间；
2. **字符串值内部含未转义的裸双引号** —— 中文输出尤其常见（`"title": "他说"你好""`）。

这两种情况下 `json.loads` 必然抛错。若直接降级到演示模板，用户看到的就是一份
无关的假行程 —— 明明模型已经生成了 90% 的正确内容。

本模块提供纯函数式的五层容错链路，从"最无损"到"最激进"逐层尝试：

    ① 原文（去代码围栏 / 零宽字符 / 中文弯引号）
    ② 切成第一个 `{` 到最后一个 `}` 的区间
    ③ 修复未转义引号
    ④ 截断修复（回退到最后一个完整值 + 补齐未闭合括号）
    ⑤ 截断修复 + 引号修复

全部失败才由调用方决定是否请模型修补（`parse_json_tolerant` 不负责发请求，
保持纯函数、可单测）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("shared.llm.json_repair")

__all__ = [
    "sanitize_json_str",
    "fix_unescaped_quotes",
    "repair_truncated_json",
    "parse_json_tolerant",
]

# 零宽字符 / BOM —— 模型或复制粘贴带进来的隐形字符，会让 json.loads 报
# "Expecting value: line 1 column 1"，报错信息完全看不出真因
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u2060"), None)

# 中文/全角引号 → 直引号（仅替换成对包裹用的引号字符本身）
_SMART_QUOTES = {
    "\u201c": '"', "\u201d": '"',   # “ ”
    "\u2018": "'", "\u2019": "'",   # ‘ ’
    "\uff02": '"',                  # ＂
}

# 字符串结束后出现这些字符，说明这个字符串是「完整的 JSON 值」；
# 否则（后面还是普通文字）就说明它是值内部的裸引号
_VALUE_TERMINATORS = (",", ":", "}", "]")


def sanitize_json_str(text: str) -> str:
    """第 ① 层基础清理：去零宽字符、去 markdown 代码围栏、中文引号归一。"""
    if not text:
        return ""
    s = text.translate(_INVISIBLE)
    # 前导 ```json / ``` 与尾部 ```
    s = re.sub(r"^\s*```[A-Za-z0-9_-]*\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    for src, dst in _SMART_QUOTES.items():
        s = s.replace(src, dst)
    return s.strip()


def fix_unescaped_quotes(text: str) -> str:
    """第 ③/⑤ 层：把字符串值内部未转义的裸双引号转义掉。

    逐字符状态机。在字符串内部遇到 `"` 时向后看第一个非空白字符：
      - 是 `,` `:` `}` `]` 或已到末尾 → 判定为**字符串结束**
      - 是普通字符         → 判定为**值内部的裸引号**，转义为 `\\"`
    """
    if not text:
        return text
    out: List[str] = []
    n = len(text)
    in_str = False
    escaped = False
    i = 0
    while i < n:
        ch = text[i]
        if escaped:
            out.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            i += 1
            continue
        if ch != '"':
            out.append(ch)
            i += 1
            continue

        if not in_str:
            in_str = True
            out.append(ch)
        else:
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            nxt = text[j] if j < n else ""
            if nxt in _VALUE_TERMINATORS or nxt == "":
                in_str = False
                out.append(ch)
            else:
                out.append('\\"')   # 值内部的裸引号
        i += 1
    return "".join(out)


def _scan_safe_points(text: str) -> Tuple[int, List[str]]:
    """扫描出"最后一个完整值"的位置，以及该位置的未闭合括号栈。

    返回 (safe_pos, safe_stack)。safe_pos 是「值刚写完」的下标，
    把它之前的内容截出来、再按 safe_stack 逆序补齐括号，就能得到合法 JSON。

    关键点：字符串分**键**和**值**两种，只有值写完才算安全点，否则会产出
    `{"title"}` 这种键没有值的非法结构。判定规则：
      - 字符串后面跟 `:` → 是键，不算安全点
      - 字符串处于对象内、且上一个有意义字符是 `{` 或 `,`、后面又已到末尾
        → 猜它是键，不算安全点
    """
    stack: List[str] = []
    n = len(text)
    i = 0
    safe_pos = 0
    safe_stack: List[str] = []
    last_sig = ""       # 最近一个非空白有意义字符

    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch in ",:":
            last_sig = ch
            i += 1
            continue
        if ch in "{[":
            stack.append(ch)
            last_sig = ch
            i += 1
            continue
        if ch in "}]":
            if stack:
                stack.pop()
            last_sig = ch
            i += 1
            safe_pos, safe_stack = i, list(stack)
            continue
        if ch == '"':
            j = i + 1
            esc = False
            while j < n:
                cj = text[j]
                if esc:
                    esc = False
                elif cj == "\\":
                    esc = True
                elif cj == '"':
                    break
                j += 1
            if j >= n:
                break                      # 字符串没闭合 → 截断点就在这里
            k = j + 1
            while k < n and text[k] in " \t\r\n":
                k += 1
            nxt = text[k] if k < n else ""
            is_key = nxt == ":" or (
                nxt == "" and bool(stack) and stack[-1] == "{" and last_sig in "{,"
            )
            last_sig = '"'
            i = j + 1
            if not is_key:
                safe_pos, safe_stack = j + 1, list(stack)
            continue
        # 数字 / true / false / null 等裸标量
        j = i
        while j < n and text[j] not in ",:}] \t\r\n":
            j += 1
        i = j
        last_sig = "v"
        safe_pos, safe_stack = i, list(stack)

    return safe_pos, safe_stack


def repair_truncated_json(text: str) -> str:
    """第 ④/⑤ 层：截断修复 —— 回退到最后一个完整值，再补齐未闭合的 `]` `}`。

    例：`{"days": [{"date": "2026-09-14", "activities": [` 这种"括号开到一半"
    的输出，会退到 `"2026-09-14"` 这个完整值，补成
    `{"days": [{"date": "2026-09-14"}]}`。
    """
    if not text:
        return text
    s = text.rstrip()
    safe_pos, safe_stack = _scan_safe_points(s)
    if safe_pos <= 0:
        return s
    if safe_pos < len(s):
        s = s[:safe_pos].rstrip()
        # 尾部残留的逗号/冒号后面本来还该有内容，去掉
        while s and s[-1] in ",:":
            s = s[:-1].rstrip()
    for opener in reversed(safe_stack):
        s += "}" if opener == "{" else "]"
    return s


def parse_json_tolerant(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """五层容错解析。

    Returns:
        (data, layer) —— 成功时 layer 为命中的层名（便于埋点统计哪一层最常救场）；
                        全失败返回 (None, "")。
    """
    if not text:
        return None, ""

    cleaned = sanitize_json_str(text)
    if not cleaned:
        return None, ""

    # ② 切成第一个 { 到最后一个 } 的区间（最常见的噪声形态：前后带解释性文字）
    if "{" in cleaned:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        core = cleaned[start:end + 1] if end > start else cleaned[start:]
    else:
        core = cleaned

    # 候选按「从最无损到最激进」排序
    candidates: List[Tuple[str, str]] = [("原文", cleaned)]
    if core and core != cleaned:
        candidates.append(("区间切片", core))

    fixed_quotes = fix_unescaped_quotes(core)
    if fixed_quotes != core:
        candidates.append(("修复未转义引号", fixed_quotes))

    repaired = repair_truncated_json(core)
    if repaired != core:
        candidates.append(("截断修复", repaired))
        repaired_fixed = fix_unescaped_quotes(repaired)
        if repaired_fixed != repaired:
            candidates.append(("截断+引号修复", repaired_fixed))

    seen = set()
    for layer, cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            if layer != "原文":
                logger.info(f"JSON 容错解析命中「{layer}」层")
            return data, layer

    # 最后一层：正则暴力提取（对前后夹带大量散文的情况兜底）
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        for layer, cand in (
            ("正则提取", m.group(0)),
            ("正则+截断修复", repair_truncated_json(m.group(0))),
        ):
            try:
                data = json.loads(cand)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict):
                logger.info(f"JSON 容错解析命中「{layer}」层")
                return data, layer

    return None, ""
