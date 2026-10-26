# 第一批路线优先迭代：第二轮独立复验

日期：2026-10-24。结论：**部分通过；上一轮5条反例已通过，但新增解除契约仍有两项 P1 防护缺陷，本批暂不全部放行。**

PI1-1 的“默认遗漏即解除”已修复，PI1-2 的指定酒店远距提示已补上。新的问题不在默认保留，而在把取消／新旅行补丁当作可信操作之前，对原文的否定语义、目标和作用范围校验不足。

## 1. 实际执行

- 上一轮独立5项：**5 passed，0.54秒**。明确酒店／餐厅被漏回时仍保留，最终违约返回needs_revision；指定酒店约74km的风险已在草案warnings出现；草案有界修正两项继续通过。
- 最新完整后端：**293 passed、11 skipped，1.85秒**。
- 前五轮57项独立不变量：**57 passed，0.74秒**。
- 新增独立解除测试11项：**2 passed、9 failed，0.58秒**。9个失败归为两项根因，不是9个独立缺陷。2个正常、具名取消用例通过，说明不是要求系统完全禁止取消。
- 新测试路径 `/tmp/travel-product-iteration-1-round2/test_anchor_changes.py`，全文附后。使用真实preserve_anchors；其中一条通过真实graph／orchestrator／临时SQLite复现误解除后正式发布。
- 未修改业务代码、原会话或原报告，未重启服务、未调用真实外部API。前端本轮无对应业务变更，未重做浏览器点击或追加前端检查；上一轮lint/build通过记录不冒充本轮新检查。
- 实施方真实恢复到终局仍在推进；当前可读取的两个route-first-live JSON仍为awaiting_choice，本轮不将它们计为完整交付通过。

## 2. PI1-R2-1 · P1 · 负面原文／截断引用可以被解释成取消或新旅行

**定位：** `Backend/app/graph/anchors.py:73–80` 的reset_quote门槛，以及`:85–125` 的补丁验证。代码验证quote是本轮连续子串，但只在quote内部查少量保护短语，未验证引用在原句中的否定语义。

### 反例A：用户明确“不取消”，整句仍通过取消检查

已有H，当前用户说：`不要取消真实酒店，第二天轻松一点`。理解模型提出 `clear H`，user_quote为整句。

实际：保护列表识别“不要换／不换”等，但没有处理“不要取消”；后面的取消正则仍命中，H被清空。餐厅相同。

期望：该句明确保留原义务，clear补丁不能生效。

### 反例B：引用截掉否定词

同一句原文，模型提出的连续引用仅为 `取消真实酒店`。它确实是“不要取消真实酒店”的连续子串，却不表达原句意思。

实际：即使在quote内部增加“不要取消”的规则，截断quote也不包含否定词。当前检查接受该补丁。

完整图／SQLite反例：先保存已订H的有效行程，下一轮输入 `不要取消真实酒店，第二天轻松一点，其他不动`；理解返回上述截断clear补丁，后续输出合法H2方案。

```text
NEGATED_RELEASE completed  h2
```

新需求required_hotel为空，正式版使用h2。不是只有helper改变了字段；最终正式交付也通过了。

### 反例C：明确否定新旅行仍重置全部锚点

`anchor_reset_quote`为本轮原句 `不是新的旅行，只是重新规划第二天`，或 `不要重新开始，保留这趟行程`。

实际：正则命中“新的旅行／重新开始”就提前return，不保留旧H／R；二者在新提案为空时都被解除。当前逻辑不能证明用户要另一趟独立旅行。

期望：否定、保留原行程的表述不能触发重置；“重新规划”也不能自动等价于新旅行。

**最小修复要求：** 在当前原文的完整相关分句中验证操作与否定、保留意图，不能只验证截断引用；reset与clear／set应采用一致的保守语义门槛。无法确认时保留义务并明确澄清，不默默执行高影响解除。仍须允许用户清楚的取消／替换／新旅行，无需把所有正常修改都增加强制审批。

这不是要求正则理解所有中文；上述都是常见、明确的否定表达，且引用是系统新增安全门槛的输入。模型可能误提补丁的概率未测量，程序不应把连续子串本身当作授权证明。

## 3. PI1-R2-2 · P1 · 具名餐厅取消与补丁目标／全类范围不一致仍被接受

**定位：** `Backend/app/graph/anchors.py:90–118` 用any(old_names)确认取消依据，之后`:139–142` 直接按change.name删除一个目标或清空全部。验证对象与执行对象没有绑定。

已有必去餐厅甲、乙，本轮原文仅 `取消真实餐厅甲`。

- 模型误给 `target=restaurant, action=clear, name=""`：程序清空甲、乙，虽然原文只取消甲。
- 模型误给 `name="真实餐厅乙"`，引用仍是“取消真实餐厅甲”：程序删除乙，虽然原文没授权取消乙。

两者都有独立函数级失败断言。未额外运行这两种误目标的完整模型终局，故不声称已测到它们各自的正式发布；状态义务的错误解除已确证，后续检查只会看到解除后的需求。

**期望与最小修复：** 执行目标必须与有效原文的取消目标相同；空name的全类取消必须有“全部／所有指定餐厅”等明确范围依据。误指乙或空范围时应拒绝／忽略该补丁、保留未获授权的义务，必要时澄清，不能因为原文提到了任何旧餐厅就获得取消该类别任意对象的权力。

## 4. 已通过与下一轮门槛

已确认正常具名取消H或R可以生效，另一类别保留；原反例漏字段、地理风险和草案修正上限通过。正常明确替换、新旅行和换城市的正式回归也通过。

下一轮至少增加：

1. 不要取消／别取消／不是要取消，quote取整句和截断子串两种形式；最终模型换店时不能完成交付。
2. 否定新旅行、仅重新规划原行程不能reset；明确另一趟独立旅行仍可reset。
3. 取消甲不能删除乙，取消甲不能清空全部；明确全部取消可清空。
4. 保留正常具名取消、明确替换、跨城和原5项／57项回归。
5. 完成原12场景尚待补齐的实际浏览器恢复与正式版终局材料；独立模型替身通过不替代这些产品交互证据。

本轮无需为这些问题增加多Agent、接导航或重构完整预约系统；应先修复本次新增补丁的语义和作用域完整性。

## 附录：新增独立测试

```bash
cd Backend
PYTHONPATH=.:tests ../.venv/bin/python -m pytest -q -s -o asyncio_mode=auto /tmp/travel-product-iteration-1-round2/test_anchor_changes.py
```

以下全部断言表示期望正确行为；修复后应通过。

```python
from copy import deepcopy
import pytest
from test_closed_loop import requirements,candidate
from test_route_first import setup,db
from app.graph import anchors,pipeline,research
from app.schemas.planning import AnchorChange,RequestDecision
from app.agents import orchestrator

@pytest.mark.parametrize('target,name',[('hotel','真实酒店'),('restaurant','真实餐厅')])
@pytest.mark.parametrize('fragment',[False,True])
def test_negated_cancellation_cannot_release_anchor(target,name,fragment):
    old=requirements(required_hotel='真实酒店',required_restaurants=['真实餐厅']).model_dump();proposed=requirements()
    text='不要取消'+name+'，第二天轻松一点'
    quote='取消'+name if fragment else text
    anchors.preserve_anchors(old,proposed,[AnchorChange(target=target,action='clear',name=name,user_quote=quote)],text)
    assert proposed.required_hotel=='真实酒店' and proposed.required_restaurants==['真实餐厅']

@pytest.mark.parametrize('text',['不是新的旅行，只是重新规划第二天','不要重新开始，保留这趟行程'])
def test_negated_new_trip_cannot_reset_anchors(text):
    old=requirements(required_hotel='真实酒店',required_restaurants=['真实餐厅']).model_dump();proposed=requirements()
    anchors.preserve_anchors(old,proposed,[],text,text)
    assert proposed.required_hotel=='真实酒店' and proposed.required_restaurants==['真实餐厅']

def test_cancelling_one_restaurant_cannot_clear_unmentioned_restaurant():
    old=requirements(required_restaurants=['真实餐厅甲','真实餐厅乙']).model_dump();proposed=requirements();text='取消真实餐厅甲'
    anchors.preserve_anchors(old,proposed,[AnchorChange(target='restaurant',action='clear',name='',user_quote=text)],text)
    assert '真实餐厅乙' in proposed.required_restaurants

@pytest.mark.parametrize('target,name',[('hotel','真实酒店'),('restaurant','真实餐厅')])
def test_explicit_named_cancellation_remains_possible(target,name):
    old=requirements(required_hotel='真实酒店',required_restaurants=['真实餐厅']).model_dump();proposed=requirements();text='取消'+name
    anchors.preserve_anchors(old,proposed,[AnchorChange(target=target,action='clear',name=name,user_quote=text)],text)
    if target=='hotel':assert not proposed.required_hotel and proposed.required_restaurants==['真实餐厅']
    else:assert proposed.required_hotel=='真实酒店' and not proposed.required_restaurants

@pytest.mark.asyncio
async def test_negated_cancellation_fragment_cannot_publish_different_hotel(monkeypatch,db):
    setup(monkeypatch,req=requirements(required_hotel='真实酒店'))
    first=await orchestrator.TripOrchestrator().plan_trip('negated-release','已订真实酒店别换',interaction_mode='automatic')
    assert first['status']=='completed'
    plan=candidate();plan['hotel_evidence_id']='h2'
    setup(monkeypatch,req=requirements(pace='relaxed'),intent='modify_itinerary',plan=plan)
    physical=research.execute_search
    async def search(category,args,remaining):
        found,events,count=await physical(category,args,remaining)
        if args.get('category',category)=='hotel' and found:
            alt=deepcopy(found[0]);alt['evidence_id']='h2';alt['data'].update(id='h2',name='其他酒店');found.append(alt)
        return found,events,count
    monkeypatch.setattr(research,'execute_search',search)
    understanding=pipeline.ask_json
    async def ask(schema,instruction,context):
        result,usage=await understanding(schema,instruction,context)
        if schema is RequestDecision:result.anchor_changes=[AnchorChange(target='hotel',action='clear',name='真实酒店',user_quote='取消真实酒店')]
        return result,usage
    monkeypatch.setattr(pipeline,'ask_json',ask)
    out=await orchestrator.TripOrchestrator().plan_trip('negated-release','不要取消真实酒店，第二天轻松一点，其他不动',interaction_mode='automatic')
    print('NEGATED_RELEASE',out['status'],out['requirements']['required_hotel'],(out.get('itinerary') or {}).get('hotel_evidence_id'))
    assert out['status'] not in ('completed','degraded') or out['itinerary']['hotel_evidence_id']=='h1'

def test_cancel_patch_cannot_target_a_different_restaurant_than_quote():
    old=requirements(required_restaurants=['真实餐厅甲','真实餐厅乙']).model_dump();proposed=requirements();text='取消真实餐厅甲'
    anchors.preserve_anchors(old,proposed,[AnchorChange(target='restaurant',action='clear',name='真实餐厅乙',user_quote=text)],text)
    assert '真实餐厅乙' in proposed.required_restaurants
```
