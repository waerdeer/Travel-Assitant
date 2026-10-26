# 路线食宿检索：住宿方向过滤专项复验

日期：2026-10-25。结论：**本次小范围修复通过专项验收；不替代锚点语义第三轮的整体未通过结论。**

## 已验证内容

1. 普通路线把hotel检索转换为nearby时携带hotel_profile；MCP请求本身不接收内部profile元字段，而是接收相应检索词。
2. `search_nearby_pois` 在取最终5个候选前应用住宿名称方向筛选；与`search_hotels`复用`lodging_direction`。
3. 独立测试将7个不匹配方向结果放在正确结果之前，分别验证“中档方向排除明显民宿名称”和“民宿方向排除明显非民宿名称”，正确候选未被前5个截断吞掉。
4. 不传profile的原空间修复请求仍保留酒店／民宿混合结果，关键词行为未被此次普通路线改动强行改变。
5. 用真实`execute_search`＋真实两个工具、仅替换`_call_mcp`返回：预算0／1／2分别最多执行0／1／2次调用。周边方向筛选为空时，预算2内从around转到同方向全市text search，没有新增第三次调用。
6. 全市回退结果的category仍为hotel，保留route_draft_id；route_relation明确“全市”和“待核实”，没有把城区酒店伪称为已核实的景点周边住宿。

## 实际执行

- 新增独立专项测试：**6 passed，0.10秒**。
- 本次最新完整后端：**315 passed、11 skipped，2.11秒**。
- 测试路径：`/tmp/travel-product-iteration-1-lodging/test_lodging.py`，全文附后。
- 本轮没有真实地图调用、服务重启、业务代码或原报告修改；不是新的酒店房态／等级／价格核验。

## 保留边界

住宿方向是名称信号和搜索意图，不是星级、真实价位或适合用户预算的认证。“中档”分支主要防止明显民宿名称混入，不能证明留下的每家酒店达到中档。

筛选在API当前返回的最多20条归一化结果范围内执行，不能保证全地区全部候选召回。范围扩大后仍需后续地理与用户约束检查。

第三轮报告中的疑问／保留语境误解除P1、set目标类别P2不属于本次补丁范围，本次专项通过不能撤销它们。请以对应语义反例重新复验后再给整体放行结论。

## 复现

```bash
cd Backend
PYTHONPATH=.:tests ../.venv/bin/python -m pytest -q -o asyncio_mode=auto /tmp/travel-product-iteration-1-lodging/test_lodging.py
```

```python
import pytest
from types import SimpleNamespace
from app.graph import tools,research

@pytest.mark.asyncio
@pytest.mark.parametrize('profile',['中档','民宿'])
async def test_direction_filter_runs_before_final_five(monkeypatch,profile):
    wrong='真实民宿' if profile=='中档' else '真实酒店';right='真实酒店' if profile=='中档' else '真实民宿'
    raws=[{'id':f'wrong-{i}','name':wrong+str(i),'typecode':'100000'} for i in range(7)]+[{'id':'right','name':right,'typecode':'100000'}]
    async def call(tool,args):return SimpleNamespace(success=True,content=[{'pois':raws}]),None
    monkeypatch.setattr(tools,'_call_mcp',call)
    import json
    out=json.loads(await tools.search_nearby_pois.ainvoke({'city':'杭州市','location':'120.14,30.24','category':'hotel','hotel_profile':profile}))
    assert [x['id'] for x in out['items']]==['right']

@pytest.mark.asyncio
async def test_legacy_spatial_lookup_without_profile_keeps_original_pool(monkeypatch):
    raws=[{'id':'stay','name':'真实民宿','typecode':'100000'},{'id':'hotel','name':'真实酒店','typecode':'100000'}]
    calls=[]
    async def call(tool,args):calls.append((tool,args));return SimpleNamespace(success=True,content=[{'pois':raws}]),None
    monkeypatch.setattr(tools,'_call_mcp',call)
    import json
    out=json.loads(await tools.search_nearby_pois.ainvoke({'city':'杭州市','location':'120.14,30.24','category':'hotel'}))
    assert [x['id'] for x in out['items']]==['stay','hotel']
    assert calls[0][1]['keywords']=='酒店'

@pytest.mark.asyncio
@pytest.mark.parametrize('budget',[0,1,2])
async def test_real_executor_and_tools_share_fallback_budget(monkeypatch,budget):
    calls=[]
    async def call(tool,args):
        calls.append((tool,args))
        poi={'id':'stay','name':'真实民宿','typecode':'100000'} if tool==tools.TOOL_AROUND else {'id':'hotel','name':'城区酒店','typecode':'100000'}
        return SimpleNamespace(success=True,content=[{'pois':[poi]}]),None
    monkeypatch.setattr(tools,'_call_mcp',call)
    facts,trace,count=await research.execute_search('nearby',{'city':'杭州市','location':'120.14,30.24','category':'hotel','hotel_profile':'中档','route_draft_id':'draft-x','route_relation':'参照西湖周边'},budget)
    assert count==len(calls)==budget
    if budget<2:assert not facts and all(name==tools.TOOL_AROUND for name,_ in calls)
    else:
        assert [name for name,_ in calls]==[tools.TOOL_AROUND,tools.TOOL_TEXT_SEARCH]
        assert facts and facts[0]['category']=='hotel'
        assert '全市' in facts[0]['data']['route_relation'] and '待核实' in facts[0]['data']['route_relation']
        assert facts[0]['data']['route_draft_id']=='draft-x'
        assert calls[1][1]['citylimit'] is True
```
