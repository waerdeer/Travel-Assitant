# 第一批路线优先产品迭代：独立验收

日期：2026-10-24。依据：本批既定 `product-iteration-1-acceptance.md`、当前工作区代码、正式测试、独立反例及实施方已产生的实时QA材料。

**结论：部分通过，存在1项 P1 阻断缺陷和1项 P2 草案提示遗漏，暂不宣称本批全部验收通过。**

主流程已经是实质的路线优先，而非改文字动画：默认入口先游览检索、构建独立草案并经SSE发布，再补坐标与食宿；用户不先选店也能看见路线。问题主要在明确锚点的跨轮保护，不能只依赖后续理解模型完整复述旧字段。

## 1. 本轮执行与证据来源

- 最新完整后端重跑：**287 passed、11 skipped，2.08秒**；其中 `test_route_first.py` 单独重跑 **20 passed，0.71秒**。
- 前五轮独立回归重放：**57 passed，0.60秒**。这些保持原路径的不变量，不能全部等同于新route_first链路的组合覆盖。
- 新增 `/tmp/travel-product-iteration-1/test_product_adversarial.py`：**2 passed、3 failed，0.59秒**。两个失败为酒店／餐厅同一跨轮根因，第三个失败为指定酒店地理风险未提示；不是三个独立P1。
- 新增通过项专门检查草案修正：最多两次RouteDraft模型返回，一次反馈修正；无效草案不出现在任何可见route_draft事件中；第二次仍无效则blocked，没有普通食宿阶段或正式版。
- 前端lint/build重新运行通过。
- 独立检查了保存的真实浏览器截图 `docs/screenshots/route-first-live-draft.png`：可见两日草案、来源、检索时间、“尚未定稿”和待检查事项，且界面仍在规划中。该浏览器操作由实施方完成，本轮是对截图的独立视觉复核，不冒充独立重做了实际点击。
- 当前实时记录 `route-first-live-qa.json`、`route-first-live-waiting.json` 可见等待选择；完整恢复到交付的实时／浏览器验收当时仍由实施方推进。不能把尚未完成的环节提前写成通过。
- 没有改业务代码／依赖／旧报告，没有重启8000／5173，没有操作原用户会话。使用真实graph／orchestrator／临时SQLite和确定性模型、搜索替身；唯一新增交付文档为本文。

实施方在审查期间增加了草案有界修正、choice_review早返回修复及酒店局部修改偏好上下文；最终测试和反例已在包含这些改动的工作区重跑。

## 2. 按十二场景逐项裁决

| 场景 | 裁决 | 依据／限制 |
| --- | --- | --- |
| A01 首次路线价值 | 通过主路径 | 调用序列、SSE及orchestrator测试证明draft早于普通食宿research；真实截图可见草案 |
| A02 不想选具体店 | 通过自动行为 | automatic完整图无选择暂停；guided保留一键自动与分类automatic模式 |
| A03 guided上下文 | 后端通过；完整浏览器恢复待补齐 | pending绑定draft、卡片有route_relation；恢复只调用Itinerary。实时重启恢复＋选择后的完整可见流程尚需最终材料 |
| A04 软偏好 | 结构化行为通过 | prefer不进入排他所选池，候选模式含明确语义；本轮没有独立测自然语言偏好分类概率 |
| A05 明确住宿锚点 | **不通过跨轮保护** | 同一轮最终模型换店能挡住，但后续只改节奏时理解模型遗漏required_hotel，程序即清空，见PI1-1 |
| A06 明确餐厅锚点 | **不通过跨轮保护** | 同轮至少一次、非排他检查存在；后续理解遗漏字段可消解义务并遗漏餐厅，见PI1-1 |
| A07 草案真假边界 | 部分通过 | 引用／日期／重复／缺源校验、无效草案修正均通过；已知指定酒店远离活动无草案提示，见PI1-2 |
| A08 失败保护 | 后端通过；停止／导出浏览器未独立重做 | 原正式Trip不被失败草案写入；源码区分draft与saved，当前独立反例中的P1是“误通过后正式覆盖”，不是正常失败分支覆盖 |
| A09 等待后恢复 | 自动化通过；完整浏览器材料待补齐 | SQLite持久化草案／pending、新orchestrator恢复通过；旧历史无draft兼容代码存在 |
| A10 旧决策／串线 | 核心后端通过 | draft_id、requirements_key、token验证；旧范围和重复提交前轮重放通过。切换会话UI源码清理存在，未独立点选验证 |
| A11 已知关闭及TTL | 原路径不变量通过；新链路全组合覆盖未全做 | 57项独立回归通过；不把这些全称为route_first新链路的实时组合通过 |
| A12 API／输入门槛 | API自动化通过；语义稳定性未评估 | HTTP／SSE及历史草案一致性、正式Trip未生成测试通过；理解澄清仍依赖模型与原范围策略，不宣称任意自然语言都已测试 |

## 3. PI1-1 · P1 · 非锚点修改可因模型漏字段静默解除已订酒店／必去餐厅

**定位：** `Backend/app/graph/pipeline.py:116–120` 直接接收完整RequestDecision.requirements，`:204` 使用req.model_dump替换当前requirements；`schemas/planning.py` 中 required_hotel／required_restaurants均有空默认值。`anchors.py`、`selected_constraint_issues()`只检查替换后的新需求。

**触发与真实业务路径：**

1. 首轮用户说“已订真实酒店，别换”或“一定要去真实餐厅”。确定性理解正确返回对应required字段，完整图自动生成并保存合法正式版。
2. 同一会话用户只说“第二天轻松一点，其他不动”。理解返回同城、同日期、relaxed的合法Requirements，但遗漏旧required字段，Pydantic补成空值。
3. 当前程序把这当成用户解除约束，没有要求明确变更或确认。后续模型输出另一家合法h2酒店，或全程改为r2餐厅。
4. 全部校验通过并发布completed新正式版，旧required义务消失。

**独立输出：**

```text
LOST_ANCHOR hotel completed  [] h2
LOST_ANCHOR restaurant completed  [] h1
```

空字符串和空列表分别为新的required_hotel／required_restaurants。酒店分支实际用h2；餐厅分支实际所有餐饮改为r2、没有r1。每个分支都经过真实SQLite存取与新orchestrator，而非只调用校验helper。

**期望：** 只改节奏时，已有明确酒店／餐厅义务继续存在。理解模型漏回字段不等于用户取消；若该轮最终规划违约，应修复或阻断，不得以新的空需求绕过程序检查。

**为何不是把任意模型错误都当程序缺陷：** 本批目标明确要求可执行的锚点保护。新增单轮校验能挡住规划模型遗漏，但同一义务可在理解节点被默认空值解除；程序没有“未提及”与“明确取消”的状态语义，因此保护链不闭合。测试没有证明真实模型每次都会遗漏，也不估算发生率。

**最小修复方向：** 让已确认锚点作为持久义务保存，对非相关修改合并保留；增加明确的新增／替换／解除意图或字段更新契约，区分未提及和用户明确取消。用户确实要求换店时仍能修改，无法判断是否解除时澄清。不要只加强“请保留旧字段”的提示词，也不要永久锁死旧锚点。

**必须复验：** 酒店与餐厅各覆盖“理解漏字段＋节奏修改”“最终模型故意换／漏店”“用户明确取消或替换可生效”“换城市／新旅行不继承旧锚点”“刷新／新实例后仍保留义务”。

## 4. PI1-2 · P2 · 指定酒店已知远离主要活动，草案仍没有对应风险提示

**定位：** `Backend/app/graph/drafts.py:23–71`。check_draft只比较同日连续景点之间的距离；anchor_issues仅核对酒店存在、唯一性与最终引用，未检查草案与酒店的地理关系。

**触发：** 指定酒店H有效、同城且有坐标，但与草案主要活动直线距离明显超过30公里；每天各一个附近景点，故景点之间不触发同日距离检查。

**实际：** 草案和食宿候选正常展示，`route_draft.warnings=[]`。用户已有酒店，也没有酒店比较入口；要到后续完整行程校验才可能发现不适合现有住宿。

**期望：** 不必在草案阶段完成真实导航，但已知的指定酒店远距关系应有明确提示或促使修正；未知坐标才标未知。不能只依赖“真实导航待核验”的通用说明掩盖已经知道的跨区风险。

**独立证据：** `test_explicit_hotel_geographic_risk_visible_in_draft` 使用h1在120.90,30.24、景点约120.14,30.24，输出 `ANCHOR_DISTANCE_WARNINGS []`。本例未继续生成正式版，**不声称最终校验会把这个远距离酒店方案放行**。

**建议修复：** 在草案地理阶段对已定位的住宿锚点和每日主要活动做现有直线距离级别的风险筛查，并把来源与未知边界送入草案warnings。无需为了本批接入真实导航，也不要解除H来让警告消失。

## 5. 正面确认与剩余交互建议

- 草案作为独立schema，有日期、引用、数量、必去排除检查；不是拿不完整Itinerary强行通过正式校验。
- SSE实际包含早期route_draft，pending与draft_id／requirements_key绑定，并有真实节点开始事件；方向符合用户“不要先选完才等待”的需求。
- prefer／lock／automatic已在UI与后端区分，required_restaurants至少一次而非排他池，保留了合理的自主安排空间。
- 草案修正只允许一次业务反馈修正，无效草案不会先展示，父deadline与工具预算仍由外层控制。
- 实时截图的rationale出现了“attraction证据”等工程措辞。建议改为“已检索的景点”，把证据ID和执行细节放展开区；这是文案完善建议，不另计阻断缺陷。
- 图片和逐餐编辑仍是后续项；本轮不因未实现它们而判失败。

## 6. 本轮最小修复与再次提交要求

优先修PI1-1，补足明确解除契约及跨轮反例；PI1-2可用现有坐标粗筛补提示。保留已通过的调用顺序、草案修正上限与旧不变量。提交复核时附上浏览器草案可见、选择恢复、失败／停止与正式导出边界的最后材料；未完成的实时步骤不要以fixture替代描述。

不要求一次实施完整的通用约束引擎，但明确锚点不能由一次全量需求重写的默认空值无声消解。

## 附录：本轮独立反例与草案修正测试

代码保存到 `/tmp/travel-product-iteration-1/test_product_adversarial.py`，运行：

```bash
cd Backend
PYTHONPATH=.:tests ../.venv/bin/python -m pytest -q -s -o asyncio_mode=auto /tmp/travel-product-iteration-1/test_product_adversarial.py
```

断言均为期望正确行为；本轮3失败、2通过。fixture复用正式测试仅用于构造合法证据与物理调用替身，执行的是生产graph／orchestrator／SQLite。

```python
from copy import deepcopy
import pytest
from test_closed_loop import candidate, requirements
from test_route_first import setup, db
from app.agents import orchestrator
from app.graph import research, drafts

@pytest.mark.asyncio
@pytest.mark.parametrize('anchor',['hotel','restaurant'])
async def test_pace_edit_cannot_erase_existing_explicit_anchor(monkeypatch,db,anchor):
    req=requirements(required_hotel='真实酒店') if anchor=='hotel' else requirements(required_restaurants=['真实餐厅'])
    setup(monkeypatch,req=req)
    first=await orchestrator.TripOrchestrator().plan_trip('anchor-persist','已订真实酒店，别换' if anchor=='hotel' else '一定要去真实餐厅',interaction_mode='automatic')
    assert first['status']=='completed'
    changed=candidate()
    if anchor=='hotel':changed['hotel_evidence_id']='h2'
    else:
        for day in changed['days']:
            for stop in day['stops']:
                if stop['evidence_id']=='r1':stop['evidence_id']='r2'
    # Valid structured understanding response omits the old required field.
    setup(monkeypatch,req=requirements(pace='relaxed'),intent='modify_itinerary',plan=changed)
    physical=research.execute_search
    async def search(category,args,remaining):
        found,events,count=await physical(category,args,remaining)
        cat=args.get('category',category)
        if category!='named' and cat==anchor and found:
            other=deepcopy(found[0]);other['evidence_id']='h2' if anchor=='hotel' else 'r2';other['data'].update(id=other['evidence_id'],name='其他酒店' if anchor=='hotel' else '其他餐厅');found.append(other)
        return found,events,count
    monkeypatch.setattr(research,'execute_search',search)
    second=await orchestrator.TripOrchestrator().plan_trip('anchor-persist','第二天轻松一点，其他不动',interaction_mode='automatic')
    print('LOST_ANCHOR',anchor,second['status'],second['requirements']['required_hotel'],second['requirements']['required_restaurants'],(second.get('itinerary') or {}).get('hotel_evidence_id'))
    assert second['status'] not in ('completed','degraded') or (second['itinerary']['hotel_evidence_id']=='h1' if anchor=='hotel' else any(s['evidence_id']=='r1' for d in second['itinerary']['days'] for s in d['stops']))

@pytest.mark.asyncio
async def test_explicit_hotel_geographic_risk_visible_in_draft(monkeypatch):
    from langchain_core.messages import HumanMessage
    from test_route_first import initial
    graph,calls=setup(monkeypatch,req=requirements(required_hotel='真实酒店'))
    physical=research.execute_search
    async def search(category,args,remaining):
        found,events,count=await physical(category,args,remaining)
        for e in found:
            if e['category']=='hotel':e['data']['location']='120.90,30.24'
        return found,events,count
    monkeypatch.setattr(research,'execute_search',search)
    result=await graph.ainvoke(initial())
    assert result['status']=='awaiting_choice'
    print('ANCHOR_DISTANCE_WARNINGS',result['route_draft']['warnings'])
    assert any('酒店' in w or '住宿' in w or '跨区' in w or '距离' in w for w in result['route_draft']['warnings'])

@pytest.mark.asyncio
@pytest.mark.parametrize('repair_succeeds',[False,True])
async def test_draft_repair_is_bounded_and_invalid_content_never_streamed(monkeypatch,db,repair_succeeds):
    from test_route_first import route
    from app.schemas.planning import RouteDraft
    setup(monkeypatch)
    valid=route();invalid=deepcopy(valid);invalid['days'][0]['attraction_evidence_ids']=['invented']
    attempts=[]
    async def draft_model(schema,instruction,context):
        attempts.append(deepcopy(context))
        return RouteDraft.model_validate(valid if repair_succeeds and len(attempts)>1 else invalid),{'model_calls':1}
    monkeypatch.setattr(drafts,'ask_json',draft_model)
    events=[]
    async def event(payload):events.append(deepcopy(payload))
    result=await orchestrator.TripOrchestrator().plan_trip('bounded-draft','杭州两天',on_event=event)
    assert len(attempts)==2 and attempts[1]['validation_feedback']
    assert result['metrics']['draft_repairs']==1
    visible=[e['route_draft'] for e in events if e.get('route_draft')]
    assert all('invented' not in d['days'][0]['attraction_evidence_ids'] for d in visible)
    if repair_succeeds:assert result['status']=='awaiting_choice' and visible
    else:assert result['status']=='blocked' and not visible and not result['final_plan_md']
```
