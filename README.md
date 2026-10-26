# 旅迹 · Voyage AI

一个用于学习与秋招展示的旅行规划 Agent。模型负责理解需求、搜索策略与行程安排，程序负责证据契约、约束检查和执行边界。

**核心闭环：理解需求 → 必要澄清 → 主要活动检索 → 可见路线草案 → 自动完成日程与食宿留白 → 程序校验／有限修正 → 交付 → 按日期和地点浏览食宿。**

## 可以体验什么

- 国内单城市、1–14 天旅行规划，支持预算、节奏、每日景点上限、必去与排除地点。
- 支持明确抵离时刻和整天休息：先扣除接驳假设再排活动，晚到/早走可留空日；普通游玩日不可凭空省略，必去和预算仍需满足。仅改返程时间会保留抵达与休息要求。
- 地点来自高德 MCP，行程通过证据 ID 引用，保留来源与检索时间。
- 默认先完成行程，不必先挑酒店和餐厅；自由用餐有实际时段，住宿建议区域有当日地点来源。明确已订酒店与必去餐厅继续作为硬约束。
- 每个真实景点/餐饮/已指定酒店卡片直接展示最多2张来源图片；旧无图行程进入可视区时按同POI ID补图，失败或缺图可降级，不重跑规划。
- 每个活动地点可“浏览特色美食”，非返程日住宿处可“浏览酒店”；只读检索真实相关候选及来源图片，缺图或加载失败有占位。浏览不调用规划模型、不自动锁定候选、不改写正式行程。
- 检查日期覆盖、地点引用、时间冲突、交通留白、景点数量、每日餐饮、费用估算和粗略地理距离。
- 校验失败反馈给规划器，默认最多修正两次；缺少必去地点证据时可补充一次检索。
- 只换酒店使用独立输出契约，保留原有每日游玩安排与其他费用。
- 中文响应式工作台：真实节点进度、执行记录、行程卡片、校验提示、历史恢复和 Markdown 导出。
- SQLite 保存轮次状态，服务重启后可以继续会话。API 失败不会显示假行程。

多样性来自不同检索方向、去重与候选比较，不能把检索标签当作实际价格、评级或菜系认证。当前交付与实测见[按需浏览验收](docs/reviews/on-demand-independent-review-final-2026-10-25.md)和[运行核查](docs/reviews/on-demand-main-runtime-check.json)。此前[路线优先迭代](docs/reviews/product-iteration-1-delivery.md)保留作基线。

API 默认 `planning_strategy: "route_first"` 和 `interaction_mode: "automatic"`。SSE会提前发送 `route_draft`，最终 `plan.version` 与历史 `/conversations/{thread_id}/trip` 的 `version` 绑定同一正式计划。点击浏览：

```http
POST /api/v1/conversations/{thread_id}/browse
Content-Type: application/json
```
```json
{
  "plan_version": "正式计划的64位版本值",
  "date": "2026-10-29",
  "anchor_evidence_id": "该日活动地点的证据ID",
  "category": "restaurant"
}
```

`hotel` 用于非返程日住宿参照，`restaurant` 用于活动地点。服务端从正式计划解析坐标，不接受客户端任意经纬度；校验错日、错地点、旧版本，检索期间改版时丢弃旧结果。空结果返回空列表，供应商不可用返回可重试说明。浏览不写入会话、checkpoint或Trip。

地点卡片缺图时使用只读 `POST /api/v1/conversations/{thread_id}/place-images`，请求`{plan_version, evidence_id}`。只允许正式行程中实际使用的景点、餐厅和酒店；已有图优先，否则仅查询该POI详情，不按名称借用其他地点图片。响应`status`为`ok`、`empty`或`unavailable`，`images`最多2项，每项包含`url/source/poi_id`。并发合并、串行补取、短缓存与超时保护均独立于规划轮次。

兼容旧 `interaction_mode: "guided"`：可显式生成候选与 `pending_choice`，再提交token和选择。`hotel_mode`、`restaurant_mode`支持`prefer`、`lock`、`automatic`；锁定餐厅仍是全程限定池，不伪装成单餐预订。默认页面遇到旧等待会话时，提供“继续完成行程”，旧候选可选展开。


费用是全程人均人民币估算，不含往返目的地大交通。酒店只是搜索候选，未预订。距离检查使用坐标和直线距离，并非真实导航、路况或营业时间核验。

## 启动

需要 Python 3.12+、Node.js 20.19+ 或 22.12+。首次安装：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r Backend/requirements.lock.txt
cd Frontend
npm ci
cd ..
```

实际测试的 Python 依赖组合记录在 `Backend/requirements.lock.txt`；`requirements.txt` / `requirements-dev.txt` 用于按范围安装或升级。

配置放在 `Backend/.env`，已有配置可直接使用；新环境从根目录 `.env.example` 复制后填写真实 Key：

```env
AMAP_MAPS_API_KEY=your_amap_web_service_key
LLM_API_KEY=your_model_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

两终端启动，均在项目根目录执行：

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir Backend --host 127.0.0.1 --port 8000 --reload --reload-dir Backend
```

```bash
cd Frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

或者执行 `bash scripts/dev.sh` 一起启动。打开 [旅行工作台](http://127.0.0.1:5173)、[API 文档](http://127.0.0.1:8000/docs)。前端代理统一指向 8000。

## 验证与评估

以下命令块分别从项目根目录执行。

```bash
cd Backend
../.venv/bin/python -m pytest -q
../.venv/bin/python scripts/evaluate.py
cd ../Frontend
npm run lint
npm run build
```

真实冒烟会使用配置中的模型和高德 API，建议隔离测试数据库：

```bash
cd Backend
DATABASE_URL=sqlite+aiosqlite:////tmp/travel-demo.db ../.venv/bin/python scripts/smoke_agent.py
```

四轮依次验证澄清、生成、节奏修改和仅修改住宿。结果写入 `docs/live-smoke-report.json`，含实际状态、耗时、token、校验记录和行程。固定约束评估写入 `docs/offline-evaluation.json`，它衡量合成错误的检测能力，不代表真实生成成功率。

另可运行苏州单日、不住酒店及可靠性问答回归：

```bash
cd Backend
DATABASE_URL=sqlite+aiosqlite:////tmp/travel-single-day.db ../.venv/bin/python scripts/smoke_single_day.py
```

结果保存在 `docs/live-single-day-report.json`。当前 UI 效果与检查范围见[验收记录](docs/verification.md)。

原有网络集成用例需显式开启：`RUN_INTEGRATION=1 ../.venv/bin/python -m pytest -m integration`。默认测试不调用真实外部服务。

## 学习入口

| 文件 | 阅读目的 |
| --- | --- |
| [架构说明](docs/architecture.md) | 决策边界、主图、状态、终止条件、失败案例与现有限制 |
| [演示与面试讲解](docs/demo-and-interview.md) | 演示步骤、代码阅读顺序、常见追问 |
| [验收记录](docs/verification.md) | 自动检查、真实 API 测试、浏览器核查和未解决项 |
| `Backend/app/schemas/planning.py` | 模型、执行器、校验器共享的契约 |
| `Backend/app/graph/workflow.py` | 可见的拓扑与反馈循环 |
| `Backend/app/graph/pipeline.py` | 需求理解、规划、酒店局部更新与交付 |
| `Backend/app/api/browse.py` / `services/plan_version.py` | 按正式计划版本只读浏览与并发改版防串线 |
| `Backend/app/graph/drafts.py` / `anchors.py` | 独立路线草案契约、一次反馈修正与跨轮明确锚点保护 |
| `Backend/app/graph/choices.py` | 候选比较、持久化等待、选择校验和恢复 |
| `Backend/app/graph/research.py` / `geography.py` | 有界工具执行与按需补全坐标 |
| `Backend/app/graph/validation.py` | 无模型参与的验收条件 |
| `Backend/tests/test_closed_loop.py` | 真实图拓扑的循环、终止、恢复回归 |
| `Backend/tests/test_geography_and_api.py` | 实际发现的问题及 API 回归 |

`graph/nodes.py` 保留原版 ReAct 实验及其回归测试；当前生产图不再使用它。

## 当前边界

当前定位本地单进程学习和展示，没有用户鉴权与多租户隔离；不应直接暴露为公共服务。轮次快照支持重启后继续对话，不支持中间节点断点续跑。

主行程的地点引用经过验证，模型生成的说明文字、主题与估算依据仍可能出错。语义理解、偏好满足、真实交通和实时价格需要进一步评估，不能宣称零幻觉或保证可预订。

后续优先方向是实时导航与营业时间校验、固定真实需求集的多次评估，以及持久化图检查点；具体见架构说明。
