# 企业智行 · Corporate Journey Hub — AI 编码规范

## 核心原则（Karpathy Guidelines）

### 1. 编码前思考（Think Before Coding）
- **不假设**：在编码前确认理解需求，不假设模糊的部分
- **不隐藏困惑**：遇到不确定的地方，明确提问而不是猜测
- **呈现权衡**：展示不同方案的优劣，而不是直接选择
- **不确定就询问**：宁可多问一句，不要做错方向

### 2. 简洁优先（Simplicity First）
- 用最少的代码解决问题
- 不添加未要求的功能/抽象/灵活性
- 优先使用项目已有的库和模式
- 避免过度工程化

### 3. 精准修改（Surgical Changes）
- 只碰必须碰的代码
- 不顺手"改进"相邻代码
- 只清理自己造成的混乱
- 避免无关重构

### 4. 目标驱动执行（Goal-Driven Execution）
- 定义可验证的成功标准
- 测试优先：先写测试再写实现
- 循环验证直到达成目标
- 每次修改后运行 lint/typecheck

---

## 技术栈

### 后端
- **语言**: Python 3.10+
- **框架**: FastAPI + Uvicorn
- **AI 编排**: LangGraph (StateGraph)
- **LLM**: OpenAI 兼容多模型（混元 / DeepSeek / Qwen / GLM），支持热切换
- **Embedding**: 可插拔后端（本地 `BAAI/bge-large-zh-v1.5` / OpenAI 兼容 `/embeddings`），不可用时降级关键词检索
- **存储**: JSON 文件持久化 (BaseJsonStore)
- **测试**: pytest

### 前端
- **框架**: React 19 + Vite 8
- **样式**: Tailwind CSS 4
- **路由**: React Router 6
- **图标**: lucide-react

---

## 项目结构

```
├── shared/                    # 平台复用层
│   ├── models/               # 数据模型 (dataclass)
│   ├── store/                # 存储基类 (BaseJsonStore)
│   ├── llm/                  # LLM 管理器
│   ├── config/               # 配置管理
│   └── middleware/            # 中间件
├── services/
│   ├── core/                 # Agent 内核 · 单服务单端口 (8001)
│   ├── policy_service/       # 政策服务（规则 + RAG）
│   └── guide_service/        # 攻略服务（RAG）
├── frontend/                 # React 前端 (3001)
│   ├── src/
│   │   ├── components/       # 共享组件库
│   │   ├── pages/            # 页面组件
│   │   └── api/              # API 封装
│   └── vite.config.js
└── docs/                     # 需求文档
```

---

## 编码约定

### Python (后端)
- 使用 dataclass 定义数据模型
- Store 继承 BaseJsonStore
- API 使用 Pydantic BaseModel
- 所有接口需要 API Key 鉴权
- 降级策略：LLM 不可用时走模板兜底

### JavaScript (前端)
- 使用函数组件 + Hooks
- Tailwind CSS 原子类
- lucide-react 图标
- 组件使用 PascalCase
- API 封装在 src/api/ 目录

---

## 运行命令

```bash
# 后端启动（单服务内核 · 单端口 8001）
python launcher.py

# 前端启动
cd frontend && npm run dev

# 后端测试（仓库根目录执行）
.venv/Scripts/python.exe -m pytest --basetemp=./.pytest_tmp -q

# 前端 lint
cd frontend && npm run lint
```

---

## 提交前检查清单

- [ ] 代码符合项目现有模式
- [ ] 使用了项目已有的库和工具
- [ ] 没有添加未要求的功能
- [ ] 运行了 lint/typecheck
- [ ] 没有硬编码敏感信息
