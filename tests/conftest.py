"""根级测试共享配置：项目根加入 sys.path（供 shared 等包导入）"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
