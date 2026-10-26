# Travel-Assistant 项目长期笔记

## 项目定位
LangGraph + ReAct 多轮对话旅行规划智能体。FastAPI 后端 + React/Vite 前端，接入高德地图 MCP。

## 运行环境（本机约定）
- **后端统一使用 conda 环境 `langchain_project`（Python 3.10.20）**
  - 解释器路径：`/Users/waldell/miniconda3/envs/langchain_project/bin/python`
  - 已装：fastapi 0.136.1 / uvicorn 0.46.0 / pydantic 2.13.3 / langgraph 1.1.9 / langchain-core 1.3.0 / langchain-openai 1.2.0 / sqlalchemy 2.0.49 / aiosqlite 0.22.1
  - 实测 `import app.main` 与 `app_graph` 编译均通过。`mcp` SDK 未安装（当前走 HTTP transport，不需要）。
- 其他 conda 环境（base / stock / torchstudy / SciencePlotDrawing）不含本项目依赖，不要用。
- 前端：`Frontend/`，node_modules 已就绪，Vite 代理 `/api` → 8000。

## 启动方式
```bash
cd Backend && /Users/waldell/miniconda3/envs/langchain_project/bin/python -m uvicorn app.main:app --port 8000 --reload
cd Frontend && npm run dev
```
注意：`app/core/config.py` 的 `env_file=".env"` 相对 CWD 解析，**必须先 cd 到 Backend 目录**再启动，否则密钥读不到。

## 架构约定
- `app/graph/` 四件套分工固定：`state.py` 定义 TripState 契约 → `tools.py` 胖工具封装 → `nodes.py` 节点实现 → `workflow.py` 拓扑编译。改流程只动 workflow，改逻辑只动 nodes。
- 新增外部能力一律走 MCP：在 `app/mcp/servers.json` 注册 → `app/graph/tools.py` 包一层带 Pydantic args_schema 的工具 → 挂到对应 TOOLS 列表。
- 节点出参必须是 TripState 里的严格字段，用 `with_structured_output` 把 LLM 自由文本回填成结构体。
- ReAct 子代理统一 `recursion_limit=5` 防账单爆炸。

## 待办 / 已知问题
- [ ] `.env.example` 含真实密钥且已出现在公开仓库，需轮换密钥并改成占位符
- [ ] `.gitignore` 补 `node_modules/`，并 `git rm -r --cached Frontend/node_modules`
- [ ] `MemorySaver` 为进程内存，重启丢记忆；如需真持久化要换 SQLite checkpointer
- [ ] `app/core/config.py` 迁移到 pydantic `ConfigDict`
