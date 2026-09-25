"""根级测试共享配置：项目根与 services/ 加入 sys.path（供 shared / core 等包导入）"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SERVICES_DIR = os.path.join(ROOT, "services")
if SERVICES_DIR not in sys.path:
    sys.path.insert(0, SERVICES_DIR)
