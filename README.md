# Travel Assistant (旅行规划智能体)

这是一个基于 **LangGraph** 和 **ReAct Agent** 架构的高级多轮对话旅行规划助手。它不仅能理解用户的自然语言输入，还能自主调用外部 API (如高德地图 MCP) 搜集天气、景点、酒店与餐饮信息，最终为用户生成一份精美的 Markdown 行程单。

## 🌟 核心特性

- **多轮对话记忆**：基于 LangGraph `MemorySaver` 实现，随时修改行程，Agent 能“记住”之前的上下文（城市、草案等），绝不会从头再来。
- **意图条件路由**：内置 Router 中枢，能精准识别用户是想“全新规划”、“修改酒店”还是“普通闲聊”，并进行动态分支跳转，节省 Token 并提升响应速度。
- **ReAct 自主代理**：放弃了硬编码的 API 调用。情报收集、酒店预订、行程排版三大节点均由独立的 ReAct Agent 接管。遇到查不到酒店等异常情况，大模型会自动换词重试，具有极强的自我纠错能力。
- **MCP 工具生态**：底层接入高德地图 API，并在中间层封装了胖工具（Fat Wrapper），提供给大模型严格的 JSON Schema 契约，防止产生幻觉。

---

## 🛠️ 技术栈

- **后端**: FastAPI, LangChain, LangGraph, Pydantic, Python 3.9+
- **前端**: React 18, Vite, Tailwind CSS, Framer Motion
- **模型支持**: 兼容 OpenAI 格式 API (默认配置使用 DeepSeek-Chat，可无缝切换 GPT-4o 等)
- **底层工具**: 高德开放平台 API (通过 MCP Server 接入)

---

## 🚀 快速启动指南

### 1. 准备环境变量
在 `Backend/` 目录下创建一个 `.env` 文件（可参考 `.env.example`），并填入以下必要信息：

```env
# 高德地图 Web服务 API Key (用于天气、POI 搜索)
AMAP_MAPS_API_KEY=你的高德API_KEY

# 大模型 API Key 及配置 (兼容 OpenAI 规范)
LLM_API_KEY=你的大模型API_KEY
LLM_BASE_URL=https://api.deepseek.com/v1  # 或 OpenAI 地址
LLM_MODEL=deepseek-chat                   # 或 gpt-4o
```

*(可选进阶)* 开启 LangSmith 调试面板：
```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=你的LangSmith_API_KEY
LANGCHAIN_PROJECT=Travel-Assistant
```

### 2. 启动后端 (Backend)

建议使用 Python 虚拟环境运行后端服务：

```bash
cd Backend

# 创建并激活虚拟环境 (macOS/Linux)
python3 -m venv venv
source venv/bin/activate

# 安装所有依赖
pip install -r requirements.txt
pip install langchain-core langchain-openai langgraph

# 启动 FastAPI 服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
后端成功启动后，API 地址为：`http://localhost:8000/api/v1/chat_plan`

### 3. 启动前端 (Frontend)

请确保你已经安装了 Node.js (建议 v18+)。

```bash
cd Frontend

# 安装依赖
npm install

# 启动 Vite 开发服务器
npm run dev
```
前端成功启动后，可在浏览器访问：`http://localhost:5173`。前端已配置 Vite 代理，会自动将 `/api` 请求转发至后端的 `8000` 端口。

---

## 📁 核心目录结构

```text
Travel-Assistant/
├── Backend/                 # Python 后端
│   ├── app/
│   │   ├── api/             # FastAPI 路由层
│   │   ├── agents/          # Orchestrator (处理 thread_id 与交互)
│   │   ├── core/            # 配置管理与全局异常
│   │   ├── graph/           # 🧠 LangGraph 核心工作流
│   │   │   ├── state.py     # 全局 TypedDict 状态定义 (记忆存储契约)
│   │   │   ├── tools.py     # MCP 工具封装 (带 Pydantic 强校验)
│   │   │   ├── nodes.py     # ReAct 子代理业务逻辑
│   │   │   └── workflow.py  # 图拓扑结构与边路由编译
│   │   └── mcp/             # 底层 MCP 协议客户端
│   └── main.py              # 启动入口
│
└── Frontend/                # React 前端
    ├── src/
    │   ├── App.tsx          # 核心聊天界面逻辑
    │   └── ...
    └── vite.config.ts       # 代理配置
```
