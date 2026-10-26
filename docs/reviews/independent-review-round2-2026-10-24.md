# 第二轮独立对抗验收

日期：2026-10-24。结论：**部分通过。第一轮 F2、F3、F4 在本轮覆盖范围内通过；F1 原始反例已修复，但营业状态识别及详情查询仍有两项 P1 遗漏，本轮不作全部放行。**

没有发现 P0。两个 P1 属于“已获取明确不可用信息，但正式版本仍能使用该酒店”的同类问题，不涉及新增导航、预订或多城市功能。

## 1. 本轮实际验证与边界

- 已阅读实施响应、`test_independent_review_regressions.py` 及相关生产代码。
- 重新运行既有全部后端测试：**228 passed、11 skipped，1.77 秒**。其中已包含按正确期望改写的第一轮反例；未拿旧“断言缺陷存在”的测试要求修复后继续通过。
- 重新运行前端 lint、build，均通过。
- 独立临时测试 `/tmp/travel-independent-review-round2/test_round2.py`：**34项，20通过、14失败**。12个失败为“4种中文状态 × 3个已支持字段”的同一根因，另一个失败为该根因的完整图路径；剩余一个失败为详情停业信号丢失。**14个失败不代表14个独立缺陷，归并为下面两项 P1。**
- 通过项覆盖手动／自动、部分／全部无效、过期、跨城、类别错误、当前／旧范围版本、无进展指纹、HTTP 与持久化后的恢复、重复提交、SSE 错误返回和 accepted_plan 保护。
- 测试运行真实生产图、路由和 SQLite 持久化，模型、地图返回使用确定性替身；HTTP 使用 ASGITransport 与 `/tmp` 数据库，无真实网络费用。没有访问原用户会话，没有停止／重启服务，没有修改业务代码、依赖或原有报告。唯一新增文档是本报告；前端构建产生常规生成文件。
- 一次临时 HTTP 测试最初因 fixture 的 `modify_hotel` 意图触发 HotelRevision、而模型替身只实现 Itinerary 而失败。已把该 fixture 改为 `modify_itinerary`，重跑通过；该夹具问题不计为业务缺陷。

## 2. F1–F4 逐项结论

| 项目 | 本轮裁决 | 独立依据 |
| --- | --- | --- |
| F1 明确停业信息过滤 | **部分通过** | 原“(停业)”／“（停业）”名称、建设中及正常名称负例已通过现有回归；但状态字段漏同义值，详情来源漏信号，见 R2-1、R2-2 |
| F2 失效选择恢复及约束丢失 | **通过（已覆盖路径）** | unavailable／expired／wrongcity／wrongcategory 的手动与自动8项均在模型调用前拒绝；部分无效但存在 h2 时手动与自动均可完成且不重复理解；原独立所选硬检查与降级契约回归通过 |
| F3 旧范围 pending 绕过 | **通过（已覆盖路径）** | 删除 pending 的 scope_policy_version 后，实际 HTTP 恢复返回 awaiting_clarification、无模型调用、无正式内容；原 Trip 和 accepted_plan 保留。当前版恢复完成且只调用 Itinerary，重复 token 返回409 |
| F4 空结果重复选择无进展 | **通过（已覆盖路径）** | 正式回归覆盖从图的空周边结果产生指纹并重复拒绝；独立验证重取相同事实的时间戳不绕过限制。SQLite恢复后连续3次HTTP同选409，SSE返回error而无result，消息／token／accepted_plan不变且零模型调用 |

F2通过不代表所有来源的营业状态已正确进入可用性判断：R2-1、R2-2 正是上游没有把“不可用”正确传给 F2 的情况。

## 3. R2-1 · P1 · 中文营业状态字段使用了比名称更窄的判定集合

**定位：** `Backend/app/graph/place_policy.py:5–17`，`Backend/app/graph/tools.py:182–201`，下游 `choices.py:available_evidence/validate_selection`。

名称中有“暂停营业、暂不营业、已关闭、已停业”会被排除，但同样的文字放到函数明确支持的 `status`、`business_status`、`operating_status` 字段就不被识别。字段处理仅与较小的 `UNAVAILABLE_STATUSES` 集合比较。

**最小输入：**

```python
{"id": "h1", "name": "湖畔酒店", "typecode": "100100", "business_status": "暂停营业"}
```

**实际：** `unavailable_place()` 返回 False，`_normalize_poi()` 可保留它。独立完整图测试把该字段放在 h1 证据中，手选 h1 后返回 **completed，hotel_evidence_id=h1**。

**期望：** 已支持营业状态字段的明确关闭值应与名称负面标记一致，不能因信息处在字段而漏过。应在候选／恢复／规划前过滤，或明确阻断所选约束。

**证据：** `test_explicit_closed_status_should_be_rejected_at_normalization` 的12个参数化失败，以及 `test_chinese_closed_status_must_not_reach_formal_plan` 的完整图失败。`closed` 和“停业”的6个参数化用例通过，说明问题是已支持入口的状态同义值不一致。

**最小修复与回归：** 复用统一的明确状态值规范化策略，至少覆盖已在名称侧支持的这些状态；保留 unknown／正常营业和正常店名负例。未知数字枚举、模糊短语不应未经供应商契约直接推断。本次不要求外部 API 必然返回上述中文字段；证明的是如果它们出现在当前承诺处理的数据入口，会被漏掉，发生率未测量。

## 4. R2-2 · P1 · 详情查询已返回停业，系统仅提取坐标后仍发布原酒店

**定位：** `Backend/app/graph/geography.py:12–34`、`:77–84`、`:103–108`；流程为 `plan → geography → validate → deliver`。

**触发条件：** 初始酒店证据无坐标，名称未带关闭标记；用户选中后进入地理补全。`maps_search_detail` 返回相同 POI ID、合法坐标，以及明确的名称／状态：

```python
{"pois": [{"id": "h1", "name": "湖畔酒店(停业)",
           "business_status": "closed", "location": "120.14,30.24"}]}
```

这里使用的 `closed` 和“(停业)”都已被新的可用性函数正确支持，因此不是 R2-1 的状态同义词问题。

**实际：** `detail_location()` 只返回 location；`enrich_locations()` 仅写入坐标、坐标来源及时间，丢弃了同一次有效查询得到的明确不可用信号。后续仍看到旧名“真实酒店”，校验通过并返回 **completed，hotel_evidence_id=h1**。

独立输出：

```text
DETAIL_CLOSED_ACTUAL completed h1
evidence.data = {id: h1, name: 真实酒店, location: 120.14,30.24,
                 location_source: maps_search_detail, ...}
```

**期望：** 同 ID 的有效详情中出现明确关闭信息，必须进入证据与校验。用户选定的酒店应提示已不可用并重新确认，不可静默发布。未指定的候选可在规则允许范围内替换。没有状态信息仍可诚实保留未知，不要求新增实时营业核验 API。

**最小修复：** 对已核对身份的详情同时提取明确不可用信息并保留来源；不要只把有坐标当作唯一有效结果。过滤时不能直接删除所选证据而重新制造第一轮的“ID消失”问题，应让独立所选约束检查给出正确原因。

**必须补充的回归：** 同 ID 详情带 `(停业)`／`closed`；详情无坐标但有关闭信息；详情 ID 不同不能污染原证据；无状态正常详情保持补全；包含已锁定酒店时失败不覆盖 accepted_plan；景点／餐厅的同类已知关闭信息也应遵循统一策略。

本测试使用真实图与真实详情解析链路、替身地图返回，不代表本次从真实高德服务观察到某家酒店停业。

## 5. 下一批最小改动及复验要求

1. 修复营业状态字段与名称规则不一致，补4种中文状态在3个既有字段的预期拒绝测试及正常状态负例。
2. 在详情提取链路保留明确不可用信号，由现有约束检查阻止正式发布；增加带／不带坐标、同／不同ID和 accepted_plan 保护用例。
3. 保留本轮已通过的 F2、F3、F4 行为，不用全面禁用自动恢复或重跑所有理解来绕开问题。

没有新增独立 P2 阻断项。早期具体餐厅选择、草案渐进展示、真实导航、长行程体验仍属于原产品建议；不能因它们尚未实施就判本轮回归失败，也不能因本轮228项通过宣称产品体验已全面成熟。

## 附录：独立测试完整代码

保存下方代码到 `/tmp/travel-independent-review-round2/test_round2.py`，在项目根目录执行：

```bash
cd Backend
PYTHONPATH=.:tests ../.venv/bin/python -m pytest -q -s -o asyncio_mode=auto /tmp/travel-independent-review-round2/test_round2.py
```

失败断言已全部写成期望正确行为；修复后这些断言应该通过。HTTP 路由与 orchestrator 的会话工厂均隔离到临时 SQLite，不会访问原用户数据库。

```python
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import httpx
import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_closed_loop import candidate, install_graph
from test_human_choices import pending_state, selected
from app.graph import choices, geography, pipeline, research, workflow
from app.graph.place_policy import unavailable_place
from app.graph.tools import _normalize_poi
from app.schemas.planning import ChoiceSelection, Itinerary

@pytest.mark.parametrize('field',['status','business_status','operating_status'])
@pytest.mark.parametrize('value',['closed','停业','暂停营业','暂不营业','已关闭','已停业'])
def test_explicit_closed_status_should_be_rejected_at_normalization(field,value):
    raw={'id':'h1','name':'湖畔酒店','typecode':'100100',field:value}
    assert unavailable_place(raw), (field,value)
    assert _normalize_poi(raw) is None

@pytest.mark.asyncio
async def test_newer_detail_closed_signal_must_prevent_formal_delivery(monkeypatch):
    base=await pending_state()
    for e in base['evidence']:
        if e['category']=='hotel':e['data'].pop('location',None)
    async def detail(server,tool,args):
        return SimpleNamespace(success=True,error_code=None,retryable=False,content=[{'pois':[{'id':args['id'],'name':'湖畔酒店(停业)','business_status':'closed','location':'120.14,30.24'}]}])
    monkeypatch.setattr(geography.mcp_client,'call_tool',detail)
    graph,calls=install_graph(monkeypatch)
    out=await graph.ainvoke({**base,'messages':[HumanMessage(content='继续')],'metrics':{},'repair_count':0,'choice_selection':selected(base['pending_choice']).model_dump()})
    print('DETAIL_CLOSED_ACTUAL',out['status'],out['itinerary']['hotel_evidence_id'],next(e['data'] for e in out['evidence'] if e['category']=='hotel'))
    assert out['status'] not in ('completed','degraded')

@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['unavailable','expired','wrongcity','wrongcategory'])
@pytest.mark.parametrize('automatic',[True,False])
async def test_invalid_hotel_restore_stops_before_model(monkeypatch,kind,automatic):
    base=await pending_state()
    e=next(e for e in base['evidence'] if e['evidence_id']=='h1')
    if kind=='unavailable':e['data']['status']='closed'
    elif kind=='expired':e['fetched_at']=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()
    elif kind=='wrongcity':e['city']='成都市'
    else:e['category']='restaurant'
    graph,calls=install_graph(monkeypatch)
    selection=ChoiceSelection(token=base['pending_choice']['token'],automatic=True) if automatic else selected(base['pending_choice'])
    with pytest.raises(choices.ChoiceConflict):await graph.ainvoke({**base,'choice_selection':selection.model_dump()})
    assert not calls

@pytest.mark.asyncio
@pytest.mark.parametrize('automatic',[True,False])
async def test_partial_invalid_candidate_does_not_prevent_valid_selection(monkeypatch,automatic):
    base=await pending_state()
    h=next(e for e in base['evidence'] if e['evidence_id']=='h1')
    valid=deepcopy(h);valid['evidence_id']='h2';valid['data'].update(id='h2',name='有效酒店')
    base['evidence'].append(valid);base['pending_choice']['hotels']+=choices.shortlist([valid],'hotel',1)
    h['data']['status']='closed'
    selection=ChoiceSelection(token=base['pending_choice']['token'],automatic=automatic,hotel_evidence_id=None if automatic else 'h2',restaurant_evidence_ids=[] if automatic else ['r1'])
    graph,calls=install_graph(monkeypatch,candidates=[{**candidate(),'hotel_evidence_id':'h2'}])
    out=await graph.ainvoke({**base,'messages':[HumanMessage(content='继续')],'metrics':{},'repair_count':0,'choice_selection':selection.model_dump()})
    assert out['status']=='completed' and out['itinerary']['hotel_evidence_id']=='h2'
    assert [n for n,_ in calls]==['Itinerary']

@pytest.mark.asyncio
async def test_no_progress_fingerprint_preserves_unaffected_category(monkeypatch):
    base=await pending_state();base.update(choice_confirmed=True,selected_options={'hotel_evidence_id':'h1','restaurant_evidence_ids':['r1']},validation={'issues':[{'code':'distant_hotel'}]},spatial_repair_no_progress=True)
    review=await choices.review_options(base);state={**base,**review};pending=review['pending_choice']
    same=ChoiceSelection(token=pending['token'],hotel_evidence_id='h1',restaurant_evidence_ids=['r1'])
    with pytest.raises(choices.ChoiceConflict,match='相同条件'):choices.validate_selection(state,same)
    changed=deepcopy(state)
    for e in changed['evidence']:e['fetched_at']=datetime.now(timezone.utc).isoformat()
    with pytest.raises(choices.ChoiceConflict,match='相同条件'):choices.validate_selection(changed,same)
    assert not pending['automatic_retry_blocked']
    choices.validate_selection(state,ChoiceSelection(token=pending['token'],automatic=True))

@pytest.mark.asyncio
@pytest.mark.parametrize('legacy',[True,False])
async def test_http_scope_resume_and_accepted_plan_protection(monkeypatch,tmp_path,legacy):
    from app.agents import orchestrator
    from app.db.base import Base
    from app.db.database import get_session
    from app.db.models import AgentCheckpoint
    from app.services.persistence import persist_turn
    from app.main import app
    base=await pending_state();base['intent']=base['pending_choice']['intent']='modify_itinerary';base.update(messages=[HumanMessage(content='北疆七天' if legacy else '确认杭州两天')],metrics={},repair_count=0)
    if legacy:base['pending_choice'].pop('scope_policy_version',None)
    accepted={'itinerary':candidate(),'plan_md':'原正式版本'}
    base.update(accepted_plan=accepted,final_plan_md='原正式版本')
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "http.db"}')
    async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as session:assert await persist_turn(session,thread_id='independent-round2',user_text='原需求',state=base)
    graph,calls=install_graph(monkeypatch)
    monkeypatch.setattr(orchestrator,'async_session_factory',factory);monkeypatch.setattr(orchestrator,'app_graph',graph)
    async def sessions():
        async with factory() as session:yield session
    app.dependency_overrides[get_session]=sessions
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            old=await client.get('/api/v1/conversations/independent-round2')
            selection=selected(old.json()['pending_choice']).model_dump()
            result=await client.post('/api/v1/chat_plan',json={'thread_id':'independent-round2','selection':selection})
            assert result.status_code==200
            body=result.json();assert body['persisted']
            if legacy:
                assert body['status']=='awaiting_clarification' and not body['plan']['plan_content'] and not calls
                saved=(await client.get('/api/v1/conversations/independent-round2/trip')).json()
                assert saved['plan_md']=='原正式版本'
                async with factory() as session:
                    snap=await session.get(AgentCheckpoint,'independent-round2')
                    assert snap.state_json['accepted_plan']==accepted and not snap.state_json['pending_choice']
            else:
                assert body['status']=='completed' and [n for n,_ in calls]==['Itinerary']
            duplicate=await client.post('/api/v1/chat_plan',json={'thread_id':'independent-round2','selection':selection})
            assert duplicate.status_code==409
    finally:app.dependency_overrides.clear();await engine.dispose()

@pytest.mark.asyncio
async def test_http_no_progress_rejects_without_mutating_saved_state(monkeypatch,tmp_path):
    from app.agents import orchestrator
    from app.db.base import Base
    from app.db.database import get_session
    from app.db.models import AgentCheckpoint
    from app.services.persistence import persist_turn
    from app.main import app
    base=await pending_state();base.update(choice_confirmed=True,selected_options={'hotel_evidence_id':'h1','restaurant_evidence_ids':['r1']},validation={'issues':[{'code':'long_transfer'}]},spatial_repair_no_progress=True,messages=[HumanMessage(content='保留我的选择')])
    base.update(await choices.review_options(base))
    base.update(accepted_plan={'itinerary':candidate(),'plan_md':'旧正式版本'},final_plan_md='旧正式版本')
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "no-progress.db"}')
    async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as session:assert await persist_turn(session,thread_id='round2-no-progress',user_text='原需求',state=base)
    graph,calls=install_graph(monkeypatch)
    monkeypatch.setattr(orchestrator,'async_session_factory',factory);monkeypatch.setattr(orchestrator,'app_graph',graph)
    async def sessions():
        async with factory() as session:yield session
    app.dependency_overrides[get_session]=sessions
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            before=(await client.get('/api/v1/conversations/round2-no-progress')).json()
            payload={'thread_id':'round2-no-progress','selection':{'token':base['pending_choice']['token'],'restaurant_evidence_ids':['r1']}}
            for _ in range(3):
                r=await client.post('/api/v1/chat_plan',json=payload)
                assert r.status_code==409 and '相同条件' in r.json()['detail']
            r=await client.post('/api/v1/chat_plan/stream',json=payload)
            assert 'event: error' in r.text and 'event: result' not in r.text
            after=(await client.get('/api/v1/conversations/round2-no-progress')).json()
            assert before==after and not calls
            async with factory() as session:
                checkpoint=await session.get(AgentCheckpoint,'round2-no-progress')
                assert checkpoint.state_json['accepted_plan']==base['accepted_plan']
    finally:app.dependency_overrides.clear();await engine.dispose()

@pytest.mark.asyncio
async def test_chinese_closed_status_must_not_reach_formal_plan(monkeypatch):
    base=await pending_state()
    hotel=next(e for e in base['evidence'] if e['evidence_id']=='h1')
    hotel['data']['business_status']='暂停营业'
    graph,calls=install_graph(monkeypatch)
    try:
        out=await graph.ainvoke({**base,'messages':[HumanMessage(content='继续')],'metrics':{},'repair_count':0,'choice_selection':selected(base['pending_choice']).model_dump()})
    except choices.ChoiceConflict:
        return
    print('CHINESE_CLOSED_ACTUAL',out['status'],out['itinerary']['hotel_evidence_id'])
    assert out['status'] not in ('completed','degraded')
```
