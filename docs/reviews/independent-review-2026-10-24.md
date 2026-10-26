# 北疆修复第一轮独立对抗验收

日期：2026-10-24。结论：**部分通过；不建议将本轮描述为“北疆问题及旧状态恢复已全面修复”。**

原始的“附近查询为空，先删除证据导致所选 ID 消失”问题已有针对性修复，正常的新请求澄清和已提供的乌鲁木齐两天流程有支持证据。但独立反例发现停业过滤、失效选择恢复、旧区域状态迁移仍有遗漏；空结果后的重复选择也缺乏无进展处理。

本轮没有发现 P0。发现三项 P1 和一项 P2，均有确定性本地反例。这里的 P1 指应在宣称对应修复完整前解决，不等于已经证明线上高频发生。

## 1. 检查方法与实际结果

- 阅读当前生产图、检索、候选、可用性策略、校验、交付、前端状态显示及原回归测试。
- 复查 `docs/xinjiang-bug-regression.json`、`docs/xinjiang-bug-live-report.json`、`docs/verification.md`。这些属于已有记录，本轮没有把它们重新包装为独立真实 API 测试。
- 重新运行后端：`../.venv/bin/python -m pytest -q`，工作目录 `Backend`；**207 passed、11 skipped，2.45 秒**。
- 重新运行前端 `npm run lint`、`npm run build`；均通过。
- 在 `/tmp/travel-independent-review/test_adversarial.py` 新增临时测试，复用仓库 fixture，执行真实生产图／函数，使用确定性模型返回和空地图结果；**5 passed，0.51 秒**。这五个测试断言的是缺陷确实可达，不能解释为五个问题已经修复。
- 没有调用真实外部模型／地图，没有停止或重启服务，没有访问或修改原用户失败会话，没有改业务代码、依赖或已有文档。常规构建更新生成目录；唯一新增的评审交付物为本文。临时测试全文附在文末，避免依赖 `/tmp` 的长期保留。

反例证明的是：给定明确的旧状态或数据输入，当前程序无法保证对应不变量。它们不测量真实模型生成该状态的概率，也不声称本次在用户会话中观察到了相同故障。

## 2. 修复项逐项裁决

| 修复项 | 裁决 | 证据与边界 |
| --- | --- | --- |
| 地理修复只增补，不因空结果删除所选证据 | 通过 | `research.py:187–204` 的合并逻辑；原新增测试和本轮空结果图测试均能保留所选事实 |
| 所选候选优先展示 | 通过（已覆盖情形） | `choices.py:94–98` 按所选 ID 排序，现有多替代项回归覆盖；不等于任何状态下都能恢复成功 |
| 建设中／停业过滤，含旧候选恢复 | 部分通过 | “建设中”手选会拒绝，规划输入也过滤；但“(停业)”漏过，自动恢复与已选失效状态有遗漏，见 F1、F2 |
| 区域／多城市在检索前澄清 | 新请求路径有条件通过；旧状态不通过 | `scope_clarification` 非空时确实先澄清；已有真实记录支持原北疆输入。但旧 pending 直接走选择恢复，不进入理解，见 F3 |
| 失败节点不显示成功绿勾 | 代码审查通过 | `AgentInspector.tsx:61–85` 明确排除 failed／waiting；与已有截图、记录一致。本轮未新增浏览器交互测试 |
| 失败会话可恢复 | 入口存在；闭环部分通过 | `App.tsx:670` 起提供范围与候选恢复。原证据丢失已修复，但无新证据时同一选择可重复回到原候选，见 F4 |
| 草案／正式版边界 | 正常失败路径通过；验收规则有漏洞 | 校验失败不发布最终 Markdown，accepted_plan 不被失败候选覆盖。F1／F2 表明验证规则漏检仍会让不合格候选成为正式版 |

乌鲁木齐市区两天、改换范围且修改天数后的成功，只证明这个收敛场景成立；不能证明原北疆七天需求被满足，不能证明长行程、环线或旧快照迁移全部通过。

## 3. 已证实缺陷

### F1 · P1 · 明确的“(停业)”标记仍可进入正式酒店行程

**定位：** `Backend/app/graph/place_policy.py:3–7`，下游为 `choices.py:21–46`、`choices.py:146–148`、`choices.py:226–235`。

**触发数据／输入：** 合法候选证据中酒店名称为 `湖畔酒店(停业)`；用户手动选择它并继续。测试使用当前有效时间、合法酒店 ID 与正常同城坐标。

**实际：** 标记表包含“已停业”“暂停营业”，没有独立的“停业”。同一过滤函数被候选、手选恢复和规划输入共用，因此此名称一路通过。真实生产图接受该酒店，返回 `status=completed`，最终 Markdown 含 `湖畔酒店(停业)`。

**期望：** 明确标注停业的候选在展示／规划前被排除；旧页面提交应提示刷新，且不得写入新的正式版本。

**独立证据：** `test_bare_closed_marker_reaches_completed_plan` 输出 `BARE_CLOSED completed h1`；这是完整图路径，不只是对关键词函数的单测。

**最小修复：** 统一明确状态后缀／状态字段的识别，至少覆盖“(停业)”“（停业）”与现有已覆盖形式；用负例防止对普通合法店名过度排除。无需通过模糊判断“所有可能关门的店”扩大任务。

### F2 · P1 · 旧失效候选的自动恢复与已选约束可被降级为警告

**定位：** `Backend/app/graph/choices.py:70–87`、`:140–158`、`:184–205`、`:226–235`；`Backend/app/graph/validation.py:183–187`；`Backend/app/graph/pipeline.py:300–305`、`:372–385`。

**反例 A，自动恢复：** 旧 pending 的酒店名和对应 evidence 都是 `湖畔酒店(建设中)`，token 和时间有效；用户点击“交给 Agent 自动安排”。

**实际：** `validate_selection` 只对 `selected_ids` 里的选项检查可用性；automatic 不携带具体 ID，因此绕过该检查。规划输入过滤建设中酒店后变为空；模型返回 `hotel_evidence_id=null` 且住宿费用为正时，校验器因过滤后没有酒店证据，把 `missing_hotel` 降为 warning。整图返回 `completed`，没有酒店，而不是提示旧候选不可用或重新检索。

这不是说建设中酒店重新被安排了：过滤确实生效。缺陷是恢复入口没有识别“现有候选失效”，并且后续把由失效造成的类别消失当成普通数据不足，静默交付没有住宿地点的多日方案。

**反例 B，已选约束：** `selected_options.hotel_evidence_id=h1`，证据 h1 已标记建设中，`choice_confirmed=true`。`review_options` 检查 raw evidence 的 ID 是否存在，不检查该证据是否仍可用，因此返回 `pending_choice=None`。过滤后的规划输入没有 h1，若输出不含酒店，`pipeline.validate()` 仍返回 `passed=true`。

**期望：** “允许部分数据缺失时交付有限方案”和“用户已选项失效”必须分开。已选酒店不可用时，必须重新确认／明确阻断，不允许靠从 evidence 过滤掉它来消解用户约束。自动模式应能使用剩余有效候选，但当受影响类别已无可用候选时，应刷新或给出明确有限方案状态及说明。

**独立证据：**

```text
AUTO_CONSTRUCTION completed hotel= None issues= ['missing_hotel', 'weather_uncovered', 'estimates_only']
SELECTED_UNAVAILABLE {'pending_choice': None} True
```

**最小修复：** 恢复前统一计算可用 evidence 与 pending 集合；missing／invalid 应基于可用集合判定。独立检查所选约束的存在与有效性，不依赖“过滤后的候选池”间接实现全部约束。不要简单把所有缺酒店一律改成 error，以免破坏原有明确的降级交付契约。

### F3 · P1 · 升级前的区域游 pending 可绕过新增范围澄清

**定位：** `Backend/app/graph/workflow.py:28–38`（selection 直达 apply_selection）；`Backend/app/graph/choices.py:184–205`（恢复原意图并跳过 understand）；`Backend/app/graph/pipeline.py:162–165`（范围门槛仅在理解节点应用）。

**触发状态／输入：** 升级前留下的有效 pending：原用户只说“去北疆高级奢华游 下周一整周”，旧流程已静默写入 `city=阿勒泰`、七天日期和候选，但用户没有明确确认缩小范围。升级后，用户从旧候选点选继续。

**实际：** 恢复路径只有 `Itinerary` 模型调用，没有 `RequestDecision`。用七个合法、同城且距离可行的景点构造返回值，整图直接交付 `completed / 阿勒泰 / 7天`；没有执行新的范围澄清。

**期望：** 升级前缺少范围确认依据的 pending 不能自动被视为满足新规则。可以给快照／pending 增加策略版本与明确确认信息，对无法证明满足新范围策略的旧状态要求一次确认，而不是让所有正常恢复都重新调用理解模型。

**独立证据：** `test_legacy_regional_pending_bypasses_scope_understanding` 输出 `LEGACY_REGION completed 阿勒泰 7 ['Itinerary']`。该测试是旧状态迁移反例，**不证明新输入“北疆”当前仍会被真实模型误解**，也未改动原用户失败会话。

**最小修复：** 增加旧 pending 的策略兼容检查；保留已确认单城的正常直接恢复路径。验收时必须测试“升级前等待 → 升级后点选”，不能仅测试“新请求 → 澄清 → 新单城候选”。

### F4 · P2 · 空周边结果后的相同选择可跨轮反复消耗调用而无进展

**定位：** `Backend/app/graph/research.py:170–204`；`Backend/app/graph/choices.py:82–105`；`Backend/app/agents/orchestrator.py:56–62` 每轮重置预算与修复计数。

**触发：** 原所选餐厅与当天景点明显超过30公里；周边查询持续返回空；用户在重新出现的原候选上继续点击“按我的选择继续”。

**实际：** 事实证据正确保留，没有再变成丢失 ID；但三轮连续提交都重新生成、重新检索空结果、返回同一个餐厅池 `['r1']` 和新 token。每轮各调用一次规划模型，最后又回 `awaiting_choice`。系统的每轮有界是成立的，但没有识别跨轮业务无进展。

**期望：** 当约束、所选 ID、有效候选和冲突均未改变，明确告知“本次没有找到替代项，保留该选择仍会冲突”，提供缩小景点范围／放宽餐厅选择等实质取舍；再次以同一状态继续时不重复进行同样的昂贵计算。用户明确刷新数据或改变条件仍应可重新尝试。

**独立证据：** `EMPTY_REPEAT [['r1'], ['r1'], ['r1']] model_calls= 3 repairs= 1`。这是三个 HTTP 轮次等价的图调用，计数按 orchestrator 行为重置；并非同一图调用无限循环，也没有证明真实 API 一定永远返回空。

**最小修复：** 保存本轮冲突／候选／选择指纹与空搜索结果，输出明确的无进展原因和下一步取舍。不要通过删除选择或无声替换解决它。

## 4. 产品建议与未验证风险（不计入本轮回归缺陷）

- 先选一至三家餐厅再规划，会把较长行程限制在小候选池中。现契约允许重复餐厅且不要求用完所选项，因此“七天反复安排同一家”不自动违反当前代码契约；它属于产品合理性问题，应通过长行程任务研究，不能单独据此判此次修复失败。
- 新输入范围澄清仍依赖模型填充 `scope_clarification`。固定的 mocked decision 测试证明路由正确，不证明所有“北疆／川西／阿勒泰地区／继续原计划”等自然语言都稳定触发。本轮未重新调用真实模型，不能宣称已观察到新请求静默缩小，也不能宣称不存在这种情况。
- 现有真实记录中乌鲁木齐两天方案包含博物馆和预计交通；营业、预约、路线时间仍没有实时证据。没有查询对应场馆官方日历，故本报告不把具体日期可能闭馆定为已证实缺陷。
- 草案与正式版的正常失败隔离是有效基础；内容渐进输出、地图与局部修改尚未实施，属于上一份产品评审建议，不视为本轮新增回归。
- 前端失败状态和恢复按钮本轮为源码审查与历史材料复核。没有新增真实浏览器点击测试，不把编译通过等同于端到端交互通过。

## 5. 建议下一批最小改动及复核门槛

建议先修 F1、F2、F3，再修 F4。此批无需重做 UI、扩展多城市或更换 Agent 框架。

| 验收用例 | 必须满足的结果 |
| --- | --- |
| 新检索返回酒店 `A(停业)`；旧 pending 手动指定它 | 不进入候选／规划，旧选择明确拒绝；无正式版 |
| 旧 pending 中建设中酒店，自动安排，有其他有效酒店 | 不选建设中地点，自动使用有效证据，约束检查仍完整 |
| 同上，但酒店全部无效 | 明确刷新／无法继续或诚实的有限交付，不得普通 completed 且悄悄漏住宿 |
| 所选酒店已不可用，但 raw evidence 仍有 ID | 不能被 choice_confirmed 提前放行；不能在 validate 中静默丢掉所选约束 |
| 旧区域 pending，用户未确认缩小范围 | 恢复前进行范围兼容检查／澄清；不直接交付代表城市 |
| 当前版本已明确确认单城的有效 pending | 仍直接恢复，避免破坏现有“不重复需求理解”的成功路径 |
| 空周边结果、有效所选事实存在 | 不删除旧事实，已选候选保留且优先展示 |
| 空结果后连续提交相同选择且冲突未变 | 明确无进展并给实质取舍；不重复同一规划／检索消耗 |
| 校验未通过或恢复被拒绝 | 原 accepted_plan 不变；无新正式 Markdown；失败与等待均不画成成功交付 |
| 七天单城、必去与所选池有空间冲突 | 有界停止并说明可行性问题，不能重复景点凑天数或无声解除用户约束 |

完成后请保留现有207项回归，并将上述失败反例改为断言期望行为的正式测试。新的测试数增加不等于产品体验合格，仍需单独验证用户是否理解澄清与恢复选项。

## 附录：可复现的临时测试

在项目根目录把下方代码保存为 `/tmp/travel-independent-review/test_adversarial.py`，然后运行：

```bash
cd Backend
PYTHONPATH=.:tests ../.venv/bin/python -m pytest -q -s -o asyncio_mode=auto /tmp/travel-independent-review/test_adversarial.py
```

代码中模型返回和空查询均为测试替身，不读取密钥、不访问网络、不操作用户会话。测试按当前有缺陷的行为断言，修复后应调整为期望行为断言。

```python
from copy import deepcopy
from datetime import date, timedelta
import pytest
from langchain_core.messages import HumanMessage
from test_closed_loop import candidate, evidence, requirements, install_graph
from test_human_choices import pending_state, selected
from app.graph import choices, pipeline, research, workflow
from app.graph.place_policy import unavailable_place
from app.schemas.planning import ChoiceSelection, Itinerary

@pytest.mark.asyncio
async def test_bare_closed_marker_reaches_completed_plan(monkeypatch):
    base = await pending_state()
    for e in base['evidence']:
        if e['evidence_id']=='h1': e['data']['name']='湖畔酒店(停业)'
    base.update(await choices.review_options(base))
    assert base['pending_choice']['hotels'][0]['name']=='湖畔酒店(停业)'
    graph, calls=install_graph(monkeypatch)
    out=await graph.ainvoke({**base,'messages':[HumanMessage(content='选择这个酒店')], 'repair_count':0,'metrics':{},'choice_selection':selected(base['pending_choice']).model_dump()})
    assert out['status']=='completed'
    assert '湖畔酒店(停业)' in out['final_plan_md']
    print('BARE_CLOSED',out['status'],out['itinerary']['hotel_evidence_id'])

@pytest.mark.asyncio
async def test_automatic_legacy_construction_bypasses_resume_gate(monkeypatch):
    base=await pending_state()
    base['intent']='new_trip'; base['pending_choice']['intent']='new_trip'
    for h in base['pending_choice']['hotels']: h['name']='湖畔酒店(建设中)'
    for e in base['evidence']:
        if e['category']=='hotel': e['data']['name']='湖畔酒店(建设中)'
    selection=ChoiceSelection(token=base['pending_choice']['token'],automatic=True)
    assert choices.validate_selection(base,selection)==base['pending_choice']
    plan=candidate(); plan['hotel_evidence_id']=None
    graph,calls=install_graph(monkeypatch,candidates=[plan])
    out=await graph.ainvoke({**base,'messages':[HumanMessage(content='交给Agent自动安排')],'repair_count':0,'metrics':{},'choice_selection':selection.model_dump()})
    assert out['status']=='completed'
    assert out['itinerary']['hotel_evidence_id'] is None
    assert any(x['code']=='missing_hotel' and x['severity']=='warning' for x in out['validation']['issues'])
    print('AUTO_CONSTRUCTION',out['status'],'hotel=',out['itinerary']['hotel_evidence_id'], 'issues=', [x['code'] for x in out['validation']['issues']])

@pytest.mark.asyncio
async def test_marked_selected_evidence_omission_passes_validation():
    base=await pending_state()
    base.update(choice_confirmed=True, selected_options={'hotel_evidence_id':'h1'})
    for e in base['evidence']:
        if e['evidence_id']=='h1': e['data']['name']='湖畔酒店(建设中)'
    result=await choices.review_options(base)
    assert result['pending_choice'] is None
    plan=candidate(); plan['hotel_evidence_id']=None
    validation=await pipeline.validate({**base,'itinerary':plan,'repair_count':1})
    assert validation['validation']['passed']
    print('SELECTED_UNAVAILABLE',result, validation['validation']['passed'])

@pytest.mark.asyncio
async def test_legacy_regional_pending_bypasses_scope_understanding(monkeypatch):
    base=await pending_state()
    req=base['requirements'];req.update(city='阿勒泰',end_date='2026-11-07',duration_days=7)
    base['intent']='new_trip';base['pending_choice'].update(intent='new_trip',city='阿勒泰')
    base['messages']=[HumanMessage(content='去北疆高级奢华游 下周一整周')]
    for e in base['evidence']:e['city']='阿勒泰'
    anchor=deepcopy(base['evidence'][0]); plan=candidate();plan['city']='阿勒泰';plan['days']=[]
    for i in range(7):
        e=deepcopy(anchor);e['evidence_id']=f'cityspot-{i}';e['data']['name']=f'市区景点{i}';base['evidence'].append(e)
        plan['days'].append({'date':(date(2026,11,1)+timedelta(days=i)).isoformat(),'theme':'市区游','stops':[{'evidence_id':e['evidence_id'],'start_time':'09:00','end_time':'11:00'},{'evidence_id':'r1','start_time':'12:00','end_time':'13:00'}]})
    graph,calls=install_graph(monkeypatch,candidates=[plan])
    out=await graph.ainvoke({**base,'repair_count':0,'metrics':{},'choice_selection':selected(base['pending_choice']).model_dump()})
    assert out['status']=='completed'
    assert [name for name,_ in calls]==['Itinerary']
    print('LEGACY_REGION',out['status'],out['requirements']['city'],len(out['itinerary']['days']),[name for name,_ in calls])

@pytest.mark.asyncio
async def test_empty_nearby_same_choice_repeats_without_progress(monkeypatch):
    base=await pending_state();base['intent']='new_trip';base['pending_choice']['intent']='new_trip';base['decision']={'food_query':'当地菜'}
    for e in base['evidence']:
        if e['category']=='restaurant':e['data']['location']='120.90,30.24'
    async def empty(category,args,remaining): return [],[{'stage':'tool','tool':'nearby','ok':True,'count':0}],1
    monkeypatch.setattr(research,'execute_search',empty)
    calls=[]
    async def ask(schema,instruction,context):calls.append(schema.__name__);return Itinerary.model_validate(candidate()),{'model_calls':1}
    monkeypatch.setattr(pipeline,'ask_json',ask)
    graph=workflow.build_workflow().compile()
    options=[]
    for i in range(3):
        out=await graph.ainvoke({**base,'messages':[HumanMessage(content='保留我的选择继续')],'choice_selection':ChoiceSelection(token=base['pending_choice']['token'],hotel_evidence_id=base['pending_choice']['hotels'][0]['evidence_id'] if base['pending_choice']['hotels'] else None,restaurant_evidence_ids=[base['pending_choice']['restaurants'][0]['evidence_id']]).model_dump(),'trace':[],'metrics':{},'repair_count':0,'research_round':0,'tool_calls':0})
        assert out['status']=='awaiting_choice'
        options.append([e['evidence_id'] for e in out['pending_choice']['restaurants']]);base=out
    assert options==[['r1']]*3
    print('EMPTY_REPEAT', options, 'model_calls=',len(calls),'repairs=',out['repair_count'])
```
