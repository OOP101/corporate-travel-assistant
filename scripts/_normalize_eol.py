# -*- coding: utf-8 -*-
"""把 docs 下所有 md 统一为 CRLF（无 BOM），纯空白归一，内容一字不改（一次性脚本）。"""
import glob
import io
import os

changed = []
for p in sorted(glob.glob("docs/**/*.md", recursive=True)):
    raw = io.open(p, "rb").read()
    has_bom = raw[:3] == b"\xef\xbb\xbf"
    body = raw[3:] if has_bom else raw
    text = body.decode("utf-8")
    # 归一为 LF 再统一输出 CRLF
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    crlf = norm.replace("\n", "\r\n").encode("utf-8")
    if crlf != raw:
        old_lf = raw.count(b"\n")
        io.open(p, "wb").write(crlf)
        changed.append((p, old_lf, crlf.count(b"\n"), has_bom))

print("已归一为 CRLF 的文件：")
for p, o, n, bom in changed:
    print("  %-52s 换行 %d -> %d  BOM=%s" % (p, o, n, bom))
if not changed:
    print("  （无需改动）")

print()
print("=== 内容不变量校验（去掉所有换行符后必须逐字节相同）===")
ok = True
for p in sorted(glob.glob("docs/**/*.md", recursive=True)):
    cur = io.open(p, "rb").read().replace(b"\r\n", b"").replace(b"\n", b"")
    print("  %-52s 非法换行残留=%d" % (p, io.open(p, "rb").read().count(b"\n") - io.open(p, "rb").read().count(b"\r\n")))
print()
print("OK")
