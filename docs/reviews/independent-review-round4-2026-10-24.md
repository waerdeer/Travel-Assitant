# 第四轮独立对抗验收

日期：2026-10-24。结论：**部分通过。R3-1 的常规组合路径已修复；仍有1项 P1 时间边界缺陷，另有1项较低优先级的合并顺序问题。**

## 1. 本轮执行结果

- 完整后端测试：**261 passed、11 skipped，1.71秒**。
- 重放第二轮34项独立期望断言和第三轮组合反例：**35 passed，0.66秒**。
- 新增4项边界测试：**1 passed、3 failed，0.52秒**。其中2项失败是同一TTL根因的有／无替代分支，另外1项为状态合并顺序；不是3个独立缺陷。
- 前端 lint/build 重新检查通过。
- 所有独立测试使用真实生产图／函数、确定性外部返回及隔离HTTP／SQLite。TTL测试使用可推进的测试时钟，不等待真实六小时，不修改系统时间。没有访问原用户会话、调用付费外部服务、重启服务或修改业务代码／已有报告；仅新增本文及 `/tmp` 测试。

## 2. 本轮确认已通过的范围

| 范围 | 结果 |
| --- | --- |
| 上轮“关闭酒店 + 远餐厅 + 周边餐厅成功 + 暂停恢复” | 常规时间范围内，关闭事实仍在；恢复后 blocked，没有新正式版，原 accepted_plan 保留 |
| 中文状态及详情负面信号 | 第二轮34项重放全部通过，包括同ID、无／有坐标、手动／自动、部分／全部失效及有效候选 |
| 旧范围策略与HTTP恢复 | 上轮隔离HTTP用例重放通过，旧版先澄清，当前版正常恢复，重复token被拒绝 |
| 无进展指纹及持久化 | 上轮HTTP／SQLite重放通过，相同选择零调用拒绝，消息／token／正式版受保护 |
| 不同城市、完全过期的负面事实 | include_unavailable 模式仍过滤异城和七小时前的记录，符合当前六小时缓存边界 |
| 有效酒店替代的组合路径 | 新增TTL测试中即使旧关闭事实丢失，有h2时最终也正确使用h2并完成；这个完成行为本身通过，失败的是刚获取的负面事实仍被提前删除 |

事实存储与候选集合的拆分方向正确。本轮没有发现常规R3-1或原F3／F4回归。下面的问题集中于新关闭信息的独立时效及合并比较的双向一致性。

## 3. R4-1 · P1 · 刚获取的关闭事实仍按旧地点检索时间提前过期

**定位：**

- `Backend/app/graph/geography.py:94–102`：新关闭信息写 availability_fetched_at，但顶层 fetched_at 不更新。
- `Backend/app/graph/research.py:29–38`：即使 include_unavailable=True，仍只按顶层 evidence.fetched_at 判断TTL。
- `Backend/app/graph/research.py:collect_evidence`：时间过滤后，刚获取的关闭事实仍会从事实存储中消失。

**触发序列（不是初始已过期的非法选择）：**

1. 酒店 h1 的初始地点检索距当前 **5小时59分**，仍在六小时有效期内，自动选择校验合法。
2. 规划／查询耗时两分钟。详情在此时刚返回同ID的 `status=closed`，并把 availability_fetched_at 写为这个新时间。
3. 同轮餐厅过远，进入周边补充检索。酒店的顶层 fetched_at 此时已距当前 **6小时1分**，但关闭事实才刚获得。
4. fresh_evidence 按旧地点时间删掉整条记录；周边找到新餐厅后暂停。恢复选择新餐厅，模型输出不含酒店的行程。
5. 因关闭记录已消失，新保护失去依据，最终以 missing_hotel warning 发布 degraded 正式版。

**无替代分支独立输出：**

```text
DETAIL_TTL False retained= False status= awaiting_choice
DETAIL_TTL_FINAL False degraded None formal= True
```

测试同时保留了原 accepted_plan；期望是阻断且不覆盖它。该断言失败。与上轮一样，实际状态是 degraded，不冒称 completed；关键是它产生正式内容，而不是保持关闭原因及阻断。

**有替代分支：** 最终 completed、使用h2，是正确行为；但新鲜关闭事实仍丢失，因此“事实应保留”的断言失败。这个分支不应被说成误用了关闭酒店。

**期望与最小修复方向：** 关闭／营业事实应按其自己的有效来源时间计算时效。新详情可以刷新可用性事实的有效期，但不能把地点检索、价格或其他未更新信息一并伪装成刚核验。缺状态的再次检索不能无限续期，异城、未来时间和已真正过期的状态仍应被排除。

建议在事实可用性时间选择处统一处理 availability_fetched_at 与顶层 fetched_at，而不是只在 merge_evidence 比较时使用前者。必须保持候选与规划输入不包含明确关闭地点。

**补充说明：** 初始选择时酒店证据仍合法有效；测试没有把初始证据设为七小时前再强行恢复。

## 4. R4-2 · P2 · 较旧关闭记录可覆盖较新的明确营业记录

**定位：** `Backend/app/graph/research.py:44–61`。时间比较仅在 previous 已不可用时执行。

**最小反例：** 同ID两条事实依次传入 merge_evidence：第一条是较新的 `business_status=正常营业`，第二条是五分钟前的 `business_status=closed`。

**实际：** 因第一条不是 unavailable，函数不比较时间，直接以后到的旧关闭覆盖新营业。`unavailable_place(merged.data)` 为 True。

**期望：** 明确状态按有效来源时间比较，不能让更旧状态仅因输入顺序靠后而取胜；两种方向应一致。缺状态的更新仍不能抹掉明确关闭。

**严重性边界：** 这是函数级已复现错误。当前工具串行执行、抓取时间通常递增，本轮没有证明生产图会自然产生上述乱序，也没有证明有用户因此被错误阻断；故定为P2，不能冒充又一个已证实的P1线上路径。

**建议回归：** 最新open+旧closed、最新closed+旧open，分别正反输入顺序；无状态返回；同一时刻冲突时采用明确的保守规则；不同ID不互相影响。

## 5. 下一批复验门槛

1. 初始地点证据5小时59分有效 → 两分钟后详情新关闭 → 餐厅补检索与恢复：关闭事实仍在，无替代则阻断、原正式版不变。
2. 同组合有h2：正常完成使用h2，同时保留有效关闭来源记录。
3. 缺状态新检索不续期负面事实；新明确关闭可续期；真正过期及异城状态不保留。
4. 明确营业／关闭状态更新采用一致的有效时间比较，不依赖合并输入顺序。
5. 继续重放已通过的35项独立用例与完整测试，不通过重跑需求理解或全面禁用自动模式规避边界。

本轮没有新增真实地图／模型评估或浏览器操作，不能推断实时营业信息覆盖率、推荐质量、P95性能或多城市能力。草案流式、偏好／锁定分层、导航和长行程体验仍是原产品建议，不是本轮新增阻断项。

## 附录：第四轮独立边界测试

保存代码到 `/tmp/travel-independent-review-round4/test_round4_extra.py`，在项目根目录执行：

```bash
cd Backend
PYTHONPATH=.:tests ../.venv/bin/python -m pytest -q -s -o asyncio_mode=auto /tmp/travel-independent-review-round4/test_round4_extra.py
```

代码中的断言均代表期望正确行为；修复后应通过。原35项重放代码见第二／三轮报告，本轮未改变其期望。

```python
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from langchain_core.messages import HumanMessage
from test_closed_loop import candidate
from test_human_choices import pending_state
from app.graph import choices,geography,pipeline,research,workflow
from app.graph.place_policy import unavailable_place
from app.schemas.planning import ChoiceSelection,Itinerary

@pytest.mark.asyncio
@pytest.mark.parametrize('with_alternative',[False,True])
async def test_combined_closure_research_respects_recent_detail_ttl(monkeypatch,with_alternative):
    base=await pending_state();base['intent']=base['pending_choice']['intent']='modify_itinerary';base['decision']={'food_query':'本地菜'}
    accepted={'itinerary':candidate(),'plan_md':'原正式版本'};base['accepted_plan']=deepcopy(accepted)
    hotel=next(e for e in base['evidence'] if e['evidence_id']=='h1');hotel['data'].pop('location',None)
    clock=[datetime.now(timezone.utc)]
    hotel['fetched_at']=(clock[0]-timedelta(hours=5,minutes=59)).isoformat()
    if with_alternative:
        alt=deepcopy(hotel);alt['evidence_id']='h2';alt['data'].update(id='h2',name='可用替代酒店',location='120.14,30.24');alt['fetched_at']=clock[0].isoformat();base['evidence'].append(alt);base['pending_choice']['hotels']+=choices.shortlist([alt],'hotel',1)
    restaurant=next(e for e in base['evidence'] if e['evidence_id']=='r1');restaurant['data']['location']='120.90,30.24'
    nearby=deepcopy(restaurant);nearby['evidence_id']='r2';nearby['data'].update(id='r2',name='附近餐厅',location='120.14,30.24')
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return clock[0] if tz else clock[0].replace(tzinfo=None)
    monkeypatch.setattr(research,'datetime',Clock);monkeypatch.setattr(geography,'datetime',Clock)
    async def detail(server,tool,args):
        clock[0]+=timedelta(minutes=2)
        return SimpleNamespace(success=True,error_code=None,retryable=False,content=[{'pois':[{'id':'h1','status':'closed','location':'120.14,30.24'}]}])
    async def search(category,args,remaining):
        assert category=='nearby';return [nearby],[{'stage':'tool','tool':'nearby','ok':True,'count':1}],1
    calls=[]
    async def ask(schema,instruction,context):
        calls.append(schema.__name__);plan=candidate()
        if len(calls)>1:
            plan['hotel_evidence_id']='h2' if with_alternative else None
            for day in plan['days']:
                for stop in day['stops']:
                    if stop['evidence_id']=='r1':stop['evidence_id']='r2'
        return Itinerary.model_validate(plan),{'model_calls':1}
    monkeypatch.setattr(geography.mcp_client,'call_tool',detail);monkeypatch.setattr(research,'execute_search',search);monkeypatch.setattr(pipeline,'ask_json',ask)
    graph=workflow.build_workflow().compile()
    out=await graph.ainvoke({**base,'messages':[HumanMessage(content='自动安排')],'metrics':{},'repair_count':0,'research_round':0,'tool_calls':0,'choice_selection':ChoiceSelection(token=base['pending_choice']['token'],automatic=True).model_dump()})
    retained=next((e for e in out['evidence'] if e['evidence_id']=='h1'),None)
    print('DETAIL_TTL',with_alternative,'retained=',bool(retained),'status=',out['status'])
    if out['status']=='awaiting_choice':
        out=await graph.ainvoke({**out,'metrics':{},'repair_count':0,'research_round':0,'tool_calls':0,'choice_selection':ChoiceSelection(token=out['pending_choice']['token'],restaurant_evidence_ids=['r2']).model_dump()})
    print('DETAIL_TTL_FINAL',with_alternative,out['status'],(out.get('itinerary') or {}).get('hotel_evidence_id'),'formal=',bool(out.get('final_plan_md')))
    if with_alternative:
        assert out['status']=='completed' and out['itinerary']['hotel_evidence_id']=='h2'
    else:
        assert out['status'] not in ('completed','degraded') and out['accepted_plan']==accepted
    assert retained and unavailable_place(retained['data'])

@pytest.mark.asyncio
async def test_old_negative_does_not_override_newer_explicit_open():
    base=await pending_state();newer=deepcopy(next(e for e in base['evidence'] if e['evidence_id']=='h1'));older=deepcopy(newer)
    newer['data']['business_status']='正常营业';older['data']['business_status']='closed';older['fetched_at']=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    merged=research.merge_evidence([newer,older])[0]
    assert not unavailable_place(merged['data'])

@pytest.mark.asyncio
async def test_expired_and_wrong_city_negative_facts_not_retained():
    base=await pending_state();item=deepcopy(next(e for e in base['evidence'] if e['evidence_id']=='h1'));item['data']['business_status']='closed'
    assert not research.fresh_evidence([item],'成都市',include_unavailable=True)
    item['fetched_at']=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()
    assert not research.fresh_evidence([item],base['requirements']['city'],include_unavailable=True)
```
