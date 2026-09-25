# -*- coding: utf-8 -*-
"""Send files to the Windows Recycle Bin via SHFileOperationW + FOF_ALLOWUNDO.
Never hard-deletes. Prints per-file result.
"""
import ctypes
from ctypes import wintypes
import os
import sys

FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_NOERRORUI = 0x0400
FOF_SILENT = 0x0004


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def recycle(paths):
    shell32 = ctypes.windll.shell32
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
    shell32.SHFileOperationW.restype = ctypes.c_int
    # pFrom needs a double-NUL terminated block
    block = "\0".join(paths) + "\0\0"
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = block
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    rc = shell32.SHFileOperationW(ctypes.byref(op))
    aborted = bool(op.fAnyOperationsAborted)
    return rc, aborted


def main():
    targets = [p for p in sys.argv[1:] if p]
    existing, missing = [], []
    for p in targets:
        (existing if os.path.exists(p) else missing).append(p)
    for p in missing:
        print("  [跳过·不存在] %s" % p)
    if not existing:
        print("没有可删除的文件。")
        return
    print("--- 即将送入回收站 ---")
    for p in existing:
        print("  %s  (%d bytes)" % (p, os.path.getsize(p)))
    rc, aborted = recycle(existing)
    print("--- 结果 ---")
    print("SHFileOperationW rc=%d aborted=%s" % (rc, aborted))
    for p in existing:
        print("  %s -> %s" % ("仍存在" if os.path.exists(p) else "已移入回收站", p))


if __name__ == "__main__":
    main()
