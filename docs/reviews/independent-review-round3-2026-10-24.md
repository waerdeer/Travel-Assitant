# 第三轮独立对抗验收

日期：2026-10-24。结论：**部分通过，仍有一项 P1 组合路径缺陷，暂不全面放行。**

第二轮的34项独立期望断言全部通过。中文状态识别与同 ID 详情关闭信号的直接处理均已修复，但关闭事实在后续地理补充检索中会丢失，仍可绕过新增的“已知不可用且无替代”保护。

## 1. 实际检查结果

- 重跑后端完整测试：**252 passed、11 skipped，1.83秒**。
- 第二轮独立用例重放：**34 passed，0.58秒**。仅把详情测试的诊断日志从直接访问 `out['itinerary']` 改为安全读取，因为正确阻断后 itinerary 可以是 None；没有削弱任何期望断言。
- 第三轮新增组合测试：**1 failed**。失败断言要求已知停业且没有替代住宿时不得发布正式版本，详见 R3-1。
- 前端 lint/build 重新检查通过。
- 已复查实施响应、正式新增测试、详情解析、候选与约束判断、fresh_evidence／collect_evidence、图路由与交付。
- 本轮使用真实生产图、上一轮隔离 HTTP／SQLite 测试与确定性模型／地图替身；没有调用真实外部模型或地图，没有停止／重启服务，没有访问原用户会话。没有修改业务代码、依赖或原报告，仅新增本文；构建生成文件属常规检查产物。

## 2. 已通过的具体范围

| 项目 | 本轮结果 | 范围 |
| --- | --- | --- |
| R2-1 中文状态字段遗漏 | 通过 | 4种中文负面值在3个已支持字段均被拒绝；完整图旧选择拒绝通过；既有正常名称／状态负例通过 |
| R2-2 详情信号直接丢弃 | 直接路径通过；跨检索路径未通过 | 同 ID 的关闭信息可保留原ID／原名并记录来源；有／无坐标、酒店／餐厅／景点、错误／缺失ID、正常详情等正式回归通过。后续 research 会丢关闭事实，见 R3-1 |
| F2 所选失效和自动恢复 | 原直接反例通过；组合保护有遗漏 | 手动／自动失效、过期、跨城、错类别、有效替代均通过；自动模式已知关闭与另一项空间冲突同时出现时仍能漏保护 |
| F3 旧范围 pending | 通过（本轮覆盖） | 旧版先澄清、当前版本直达规划、accepted_plan保留、旧token重复提交409；隔离HTTP回归通过 |
| F4 相同条件无进展 | 通过（本轮覆盖） | 持久化恢复后三次相同选择均零调用拒绝，时间戳刷新不绕过指纹，SSE错误不产出result，token／消息／原正式版本保持不变 |

这里没有把旧“断言缺陷存在”的测试拿来判定新实现，也没有把正常降级方案一概视为缺陷。R3-1 的关键是系统已经获取了明确停业事实，却在另一类修复中丢掉了它。

## 3. R3-1 · P1 · 关闭酒店的负面事实在餐厅地理修复中被过滤掉

**定位：**

- `Backend/app/graph/research.py:29–38`：fresh_evidence 同时承担新鲜度检查与不可用过滤。
- `Backend/app/graph/research.py:118–120`：再次 research 以已经过滤后的集合替换事实集合。
- `Backend/app/graph/research.py:243–256`：返回的 evidence 不再包含该关闭事实。
- `Backend/app/graph/choices.py:88–100`：新增 known_closed_pool 保护依赖原 evidence 中仍存在负面事实。
- `Backend/app/graph/pipeline.py:after_validate / deliver`：另一项空间冲突先引导 research；之后降级结果仍写入 accepted_plan。

**合理的组合触发：**

1. 两日行程已有正常待选，用户选择自动安排；测试保留原正式版本用于验证覆盖行为。
2. 初稿选择酒店 h1、餐厅 r1。酒店无坐标，r1 与景点相距超过30公里。
3. 详情查询同 ID 的 h1，返回 `business_status=closed` 和合法坐标。此次新修复正确把关闭信息写入证据。
4. 校验同时得到酒店不可用／引用问题和餐厅 long_transfer，图因后者进入地理补充检索。
5. collect_evidence 调 fresh_evidence，关闭的 h1 被整个过滤掉；附近搜索返回可用餐厅 r2。没有酒店替代。
6. 图重新要求餐厅选择，用户选 r2。此时 evidence 已无酒店关闭事实，所选约束中也没有酒店ID，因为初次授权自动安排。
7. 规划返回不含酒店的方案；校验将 missing_hotel 当作普通数据缺失 warning。最终发布 degraded 正式版，覆盖 accepted_plan。

**独立输出：**

```text
AFTER_RESEARCH awaiting_choice [('a1', None), ('a2', None), ('r1', None), ('r2', None)]
AFTER_RESUME degraded None ['missing_hotel', 'weather_uncovered', 'estimates_only']
formal_md= True accepted_hotel= None
```

实际状态是 **degraded，不是 completed**。但它有正式 Markdown，且成为新 accepted_plan；已知酒店关闭信息被退化成“未能获取部分实时数据：hotel”。本轮新增的“不能靠省略已知关闭类别来交付”的保护没有生效。

测试没有假定真实模型一定返回省略酒店的方案。该返回值是当前 schema 允许的，校验器必须防止它通过；这也正是实施方新增自动无替代回归所保护的不变量。区别只在于此处多走了一次修复餐厅距离的 research。

**期望：** 在同一规划和恢复流程内保留明确不可用事实及来源。如果该必要类别没有有效替代，应明确阻断／重新检索并保留原正式版；有有效替代可正常修复。不能用餐厅的成功修复消解住宿的已知失败。

**最小修复方向：** 把“事实是否新鲜”和“事实是否可作为候选”分开：关闭事实不进入候选／规划可用集合，但应保留在事实记录或独立的可用性记录中，供 known_closed_pool 及恢复检查使用。明确刷新／覆盖状态时再按来源、时间与ID处理更新；不能简单永久锁死所有曾关闭地点，也不能把不可用项重新加入候选。

**复验至少覆盖：**

- 自动酒店详情关闭 + 远餐厅 + 附近餐厅成功 + 无酒店替代：不得发布新正式版，原 accepted_plan 不变。
- 同组合但存在有效酒店替代：可使用有效替代，关闭酒店仍不被使用。
- 餐厅／景点的明确关闭信息与另一类别的距离修复同时出现：负面事实不因 research 被删掉。
- 当前有效关闭事实持久化后恢复仍可解释原因；真正没有任何住宿来源、且没有用户指定住宿时原有警告契约仍保留。
- 明确重查得到同 ID 新状态的处理有来源与时间规则，不通过去掉字段静默“恢复营业”。

## 4. 未验证项与产品边界

- 本轮没有新增真实浏览器交互、真实高德详情或真实模型随机性评估；不能由 fixture 通过推断营业状态接口覆盖率、模型质量或真实出行可行性。
- 详情只在原有按需坐标补全流程中调用，不代表系统对所有已有坐标地点重新核验营业。当前产品不应宣称全面实时营业核验；本报告也不把缺少这项新能力计为新回归。
- 北疆七天环线、多住宿点与真实导航仍不在支持范围。旧范围恢复已通过，不表示扩大了能力。
- 草案渐进交付、偏好／锁定分层和长行程餐饮体验仍是原产品建议，本轮不要求一起实施。

## 附录：新增组合反例完整代码

下方代码保存到 `/tmp/travel-independent-review-round3/test_round3_extra.py`。项目根目录运行：

```bash
cd Backend
PYTHONPATH=.:tests ../.venv/bin/python -m pytest -q -s -o asyncio_mode=auto /tmp/travel-independent-review-round3/test_round3_extra.py
```

断言写的是修复后应满足的行为。第二轮34项代码见上一份报告，本轮仅对其诊断日志作 None 安全读取。

```python
from copy import deepcopy
from types import SimpleNamespace
import pytest
from langchain_core.messages import HumanMessage
from test_closed_loop import candidate
from test_human_choices import pending_state
from app.graph import choices,geography,pipeline,research,workflow
from app.schemas.planning import ChoiceSelection,Itinerary

@pytest.mark.asyncio
async def test_closed_hotel_fact_survives_unrelated_spatial_research(monkeypatch):
    base=await pending_state();base['intent']=base['pending_choice']['intent']='modify_itinerary';base['accepted_plan']={'itinerary':candidate(),'plan_md':'原正式版'};base['decision']={'food_query':'本地菜'}
    hotel=next(e for e in base['evidence'] if e['evidence_id']=='h1');hotel['data'].pop('location',None)
    restaurant=next(e for e in base['evidence'] if e['evidence_id']=='r1');restaurant['data']['location']='120.90,30.24'
    replacement=deepcopy(restaurant);replacement['evidence_id']='r2';replacement['data'].update(id='r2',name='附近餐厅',location='120.14,30.24')
    async def detail(server,tool,args):return SimpleNamespace(success=True,error_code=None,retryable=False,content=[{'pois':[{'id':'h1','business_status':'closed','location':'120.14,30.24'}]}])
    async def search(category,args,remaining):
        assert category=='nearby'
        return [replacement],[{'stage':'tool','tool':'nearby','ok':True,'count':1}],1
    calls=[]
    async def ask(schema,instruction,context):
        calls.append(schema.__name__)
        plan=candidate()
        if len(calls)>1:
            plan['hotel_evidence_id']=None
            for day in plan['days']:
                for stop in day['stops']:
                    if stop['evidence_id']=='r1':stop['evidence_id']='r2'
        return Itinerary.model_validate(plan),{'model_calls':1}
    monkeypatch.setattr(geography.mcp_client,'call_tool',detail);monkeypatch.setattr(research,'execute_search',search);monkeypatch.setattr(pipeline,'ask_json',ask)
    graph=workflow.build_workflow().compile()
    out=await graph.ainvoke({**base,'messages':[HumanMessage(content='自动安排')],'metrics':{},'repair_count':0,'research_round':0,'tool_calls':0,'choice_selection':ChoiceSelection(token=base['pending_choice']['token'],automatic=True).model_dump()})
    print('AFTER_RESEARCH',out['status'],[(e['evidence_id'],e['data'].get('business_status')) for e in out['evidence']])
    if out['status']=='awaiting_choice':
        out=await graph.ainvoke({**out,'metrics':{},'repair_count':0,'research_round':0,'tool_calls':0,'choice_selection':ChoiceSelection(token=out['pending_choice']['token'],restaurant_evidence_ids=['r2']).model_dump()})
    print('AFTER_RESUME',out['status'],(out.get('itinerary') or {}).get('hotel_evidence_id'),[i['code'] for i in out.get('validation',{}).get('issues',[])], 'formal_md=',bool(out.get('final_plan_md')),'accepted_hotel=',out.get('accepted_plan',{}).get('itinerary',{}).get('hotel_evidence_id'))
    assert out['status'] not in ('completed','degraded') or (out.get('itinerary') or {}).get('hotel_evidence_id')
```
