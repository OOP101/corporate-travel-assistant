---
name: karpathy-guidelines
description: Andrej Karpathy's coding principles for AI assistants - prevents common LLM coding pitfalls
globs:
  - "**/*.{py,js,jsx,ts,tsx}"
---

# Andrej Karpathy 编码规范

你在处理编码任务时，必须遵守以下核心原则。这些原则基于 Andrej Karpathy 对 LLM 编码助手常见陷阱的观察。

---

## 1. 编码前思考（Think Before Coding）

- 不假设：在编码前确认理解需求，不假设模糊的部分
- 不隐藏困惑：遇到不确定的地方，明确提问而不是猜测
- 呈现权衡：展示不同方案的优劣，而不是直接选择
- 不确定就询问：宁可多问一句，不要做错方向

**检验标准**：任务开始前，能复述需求要点并确认理解

---

## 2. 简洁优先（Simplicity First）

- 用最少的代码解决问题
- 不添加未要求的功能/抽象/灵活性
- 优先使用项目已有的库和模式
- 避免过度工程化

**检验标准**：代码改动量与任务复杂度匹配，没有多余代码

---

## 3. 精准修改（Surgical Changes）

- 只碰必须碰的代码
- 不顺手"改进"相邻代码
- 只清理自己造成的混乱
- 避免无关重构

**检验标准**：diff 中没有与任务无关的改动

---

## 4. 目标驱动执行（Goal-Driven Execution）

- 定义可验证的成功标准
- 测试优先：先写测试再写实现
- 循环验证直到达成目标
- 每次修改后运行 lint/typecheck

**检验标准**：有明确的完成标准，且通过验证

---

## 项目特定约定

### 项目名称
企业智行 · Corporate Journey Hub

### 后端技术栈
- Python 3.10+ / FastAPI / LangGraph / Uvicorn
- 数据模型使用 dataclass
- 存储继承 BaseJsonStore
- LLM 调用使用 shared/llm/manager.py

### 前端技术栈
- React 19 / Vite 8 / Tailwind CSS 4
- 组件使用 lucide-react 图标
- API 封装在 src/api/ 目录

### 关键目录
- shared/ - 平台复用层
- services/ - 微服务（journey-hub, planner-core, sense-engine）
- frontend/src/components/ - 共享组件库

---

## 禁止行为

1. **不要一次性重写整个文件**
2. **不要引入不必要的依赖**
3. **不要修改没有问题的代码**
4. **不要跳过错误处理**
5. **不要硬编码配置值**
