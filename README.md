# 旅行助手 Travel Assistant

基于 **Multi-Agent + MCP + Skills** 架构的智能旅行规划服务。用户输入目的地、日期和偏好，系统自动匹配专业领域 Skill，通过 MCP 调用外部工具获取实时数据，生成个性化行程方案。

## 技术栈

- **后端框架**: FastAPI + Uvicorn
- **数据模型**: Pydantic v2
- **异步调度**: asyncio + httpx
- **工具协议**: MCP (Model Context Protocol)
- **LLM**: OpenAI 兼容协议（可接入任意兼容服务）

## 项目结构

```
Backend/
├── app/
│   ├── main.py                  # FastAPI 启动入口
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py            # API 路由（/api/v1/trips, /api/v1/skills）
│   ├── core/
│   │   ├── config.py            # 环境配置（读取 .env）
│   │   ├── exceptions.py        # 统一异常体系
│   │   └── llm.py               # LLM 调用封装（OpenAI 兼容）
│   ├── schemas/                 # Pydantic 数据模型
│   │   ├── Attraction.py, Hotel.py, Meal.py
│   │   ├── Dayplan.py, Tripplan.py, Weather.py
│   │   ├── Budget.py, Location.py
│   │   └── __init__.py
│   ├── agents/                  # Agent 执行层
│   │   ├── base.py              # BaseAgent + AgentContext + AgentResult
│   │   ├── orchestrator.py      # 编排器（意图识别 → Skill → 生成）
│   │   ├── prompts/             # prompt 模板
│   │   └── executors/           # 执行器骨架
│   ├── mcp/                     # MCP 工具调用层
│   │   ├── client.py            # MCPClient：连接/列工具/调工具
│   │   ├── registry.py          # 全局单例
│   │   └── servers.json         # 外部 MCP Server 配置
│   ├── skills/                  # 专业领域方案层
│   │   ├── base.py              # BaseSkill 抽象基类
│   │   ├── registry.py          # SkillRegistry：注册 + 路由匹配
│   │   ├── intent_router.py     # IntentRouter：意图识别
│   │   ├── general.py           # 通用行程（兜底）
│   │   ├── family.py            # 亲子游专家
│   │   ├── budget.py            # 穷游/预算专家
│   │   └── food.py              # 美食攻略专家
│   └── tools/                   # 工具层（将被 MCP 替代）
├── requirements.txt
├── .env.example
└── README.md
```

## 环境要求

| 依赖 | 版本要求 | 用途 |
|------|---------|------|
| Python | >= 3.10（推荐 3.12） | MCP SDK 依赖 |
| Node.js | >= 18 | 高德 MCP Server 运行 |
| 高德 API Key | - | 地图/天气数据 |
| LLM API Key | - | 行程生成 |

## 快速开始

### 1. 安装依赖

```bash
# 安装 Python（如未安装 3.10+）
brew install python@3.12

# 安装 Node.js（高德 MCP Server 需要）
brew install node

# 创建虚拟环境
cd Backend
python3.12 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

### 3. 启动服务

```bash
cd Backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

服务启动后访问：
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

## API 接口

### POST /api/v1/trips — 生成旅行计划

```bash
curl -X POST http://localhost:8000/api/v1/trips \
  -H "Content-Type: application/json" \
  -d '{
    "city": "北京",
    "start_date": "2026-07-01",
    "end_date": "2026-07-03",
    "preferences": "带娃亲子游",
    "accommodation": "经济型"
  }'
```

**请求参数:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| city | string | ✅ | 目的地城市 |
| start_date | string | ✅ | 开始日期 YYYY-MM-DD |
| end_date | string | ✅ | 结束日期 YYYY-MM-DD |
| preferences | string | ❌ | 偏好：亲子游/穷游/美食等 |
| accommodation | string | ❌ | 住宿偏好 |

**响应:**
```json
{
  "plan": { "city": "北京", "start_date": "2026-07-01", ... },
  "skill_used": "亲子游"
}
```

### GET /api/v1/skills — 查看已注册的 Skill

```bash
curl http://localhost:8000/api/v1/skills
```

## 架构设计

### 调用链路

```
用户请求 → API 路由 → Orchestrator
                         │
                    IntentRouter（关键词匹配）
                         │
              ┌──────────┴──────────┐
              │   匹配到 Skill      │
              └──────────┬──────────┘
                         │
                    Skill.execute()
                    ├── MCPClient.call_tool()  ← 外部数据（景点/天气/酒店）
                    ├── 专业 prompt + 规则      ← 领域知识
                    └── LLMClient.chat()        ← 生成方案
                         │
                    返回 TripPlan
```

### Skills 路由规则

| 关键词 | 匹配 Skill | 专业能力 |
|--------|-----------|---------|
| 亲子/带娃/孩子/儿童 | 亲子游 | 安全、设施、节奏、预案 |
| 穷游/省钱/预算/经济 | 穷游预算 | 低成本交通、经济住宿、省钱技巧 |
| 美食/吃/小吃/地道 | 美食攻略 | 餐厅推荐、美食动线、预约提示 |
| （其他） | 通用行程 | 标准规划 |

### MCP 配置

`app/mcp/servers.json` 定义外部工具服务：

```json
{
  "amap": {
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "amap-maps-mcp-server"],
    "env": { "AMAP_API_KEY": "${AMAP_API_KEY}" }
  }
}
```

`${AMAP_API_KEY}` 自动从环境变量读取。

## 扩展指南

### 新增 Skill

```python
# app/skills/honeymoon.py
from app.skills.base import BaseSkill

class HoneymoonSkill(BaseSkill):
    @property
    def name(self): return "蜜月游"

    @property
    def keywords(self): return ["蜜月", "结婚", "浪漫"]

    @property
    def planner_prompt(self): return "你是蜜月游规划专家..."
```

注册到 `registry.py`：
```python
from app.skills.honeymoon import HoneymoonSkill
self._skills.append(HoneymoonSkill())
```

### 接入新 MCP Server

在 `app/mcp/servers.json` 添加配置：
```json
{
  "new_server": {
    "transport": "stdio",
    "command": "...",
    "args": [...],
    "env": { "API_KEY": "${NEW_API_KEY}" }
  }
}
```

## 开发状态

| 模块 | 状态 |
|------|------|
| Schema 数据模型 | ✅ 完成 |
| MCP 工具调用层 | ✅ 完成（需 Python 3.10+ 运行） |
| Skills 领域方案层 | ✅ 完成 |
| IntentRouter 意图识别 | ✅ 完成 |
| Orchestrator 编排器 | ✅ 完成 |
| FastAPI 入口 + 路由 | ✅ 完成 |
| LLM 接入 | ✅ 完成（需配置 API Key） |
| 测试 | 🔲 待补充 |
| 缓存/限流 | 🔲 待补充 |
