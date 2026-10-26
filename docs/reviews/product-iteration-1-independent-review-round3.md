# 第一批路线优先迭代：第三轮独立复验

日期：2026-10-25。结论：**部分通过，仍有1项 P1 阻断和1项 P2 目标类别遗漏。上一轮直接反例已修复，但尚不能全部放行。**

## 1. 本轮实际结果

- 前两轮独立反例合计16项：**16 passed，0.59秒**。原来的否定引用、空范围误删、指定目标不一致、漏字段与地理风险反例均已通过。
- 最新完整后端：**293 passed、11 skipped，1.82秒**。
- 前五轮旧不变量重放：**57 passed，0.62秒**。
- 新增9项：**4 passed、5 failed，0.76秒**。4个正常修改通过：具名取消、酒店替换、独立新旅行、所有指定餐厅取消。5个失败归为下面两个根因，不是5个独立缺陷。
- 本轮使用真实preserve_anchors及完整graph／orchestrator／临时SQLite，模型和搜索替身为确定性返回；没有新增真实API调用、浏览器点击、服务重启或业务代码修改。原报告保留，仅新增本文及 `/tmp/travel-product-iteration-1-round3/test_extra.py`。

## 2. PI1-R3-1 · P1 · 拆句丢掉请求语气与后续保留指令，疑问仍会变成取消／重置

**定位：** `Backend/app/graph/anchors.py:74` 把问号和标点直接用于拆分、丢掉语气；`:78–88` 只要任一分句匹配新旅行就reset；`:118–120` 只要相关分句匹配取消就执行，不检查用户同轮后续的保留／不要操作意图。

### 完整图复现

先保存用户已订H的正式行程。下一轮用户输入：

> 取消真实酒店？先别操作，我只是问问

模型误提clear H，quote为连续原文“取消真实酒店”。程序得到的相关分句是“取消真实酒店”，问号已经丢失；“先别操作／只是问问”在其他分句中，未进入当前取消判断。

真实生产图和SQLite最终输出：

```text
QUESTION_RELEASE completed  h2
```

新required_hotel为空，最终使用h2并完成正式发布。本例不是函数级猜测，也不只是不必要地澄清；已经走到误解除后的正式交付。

### 同根因的其他已复现输入

- `取消真实酒店，但仍然保留真实酒店`：有矛盾，至少应澄清；当前按前一分句清空。
- `开始新旅行？不是，继续原来的行程`：当前按首个去掉问号的分句reset全部锚点。

**期望：** 问句、试探、举例、同轮明确“不要操作”或保留／矛盾指令不能作为肯定式解除依据。无法确定时保留旧义务并澄清，不进入地图／规划。用户明确命令式取消与新旅行仍可执行。

**最小修复方向：** 保留分句终止符与语气，不把问句规范化成祈使句；在整条本轮请求中检查相关否定、保留、冲突和“先别操作”语境。clear、set、reset共用同一变更授权语义边界。无需声称能理解全部中文，但普通问句和明确不操作表述必须挡住。

## 3. PI1-R3-2 · P2 · set补丁未绑定目标类别

**定位：** `Backend/app/graph/anchors.py:142–157`。specify正则同时接受酒店、住宿、餐厅、饭店前缀，不取决于change.target；匹配后按change.target执行。

**输入：** 旧酒店H与原餐厅已确定；用户说 `餐厅换成湖畔饭店`。模型误给 `target=hotel, action=set, name=湖畔饭店`，quote为该原句。

**实际：** preserve_anchors把required_hotel改成湖畔饭店，即原文餐厅动作被应用到住宿。独立函数测试失败。

**期望：** 明确餐厅主体的句子不能授权酒店替换。指令主体与补丁target不一致时保留义务／澄清。类别相符的正常“酒店换成新的酒店”本轮通过，应继续支持。

**严重性边界：** 本例只验证了函数状态误改，没有额外证明真实来源会返回同名有效酒店并最终正式发布，因此列为P2，不冒充又一个已证实的发布级P1。

**修复建议：** target决定允许的主体类别与动作，或对解析得到的句子类别与target做一致性检查。明确类别不能由模型字段覆盖。

## 4. 正常修改与保守澄清的确认

本轮4个正常修改没有被锁死：`请取消真实酒店`、`酒店换成新的酒店`、`开始一趟新的旅行`、`取消所有指定餐厅`均按期望生效。上一轮的“不要取消H”整句及截断引用如今保留H；完整图返回awaiting_clarification，而不是重新规划换店。

因此当前修复已经改善默认安全性。剩余问题是未保留语气／跨句意图，以及set的类别约束，不需要推倒已通过的fullmatch／具名目标机制。

## 5. 浏览器与真实终局材料复核

本轮独立读取并核对实施方新增材料，浏览器操作由实施方执行，未冒充本轮独立重新点选。

- `route-first-live-qa.json` 当前status为completed。
- `route-first-completed-checks.json` 显示正式版通过、杭州两天、恢复阶段1次模型／5次工具、35.602秒；trace从apply_selection进入plan，没有重复understand／research。
- 直接查看 `route-first-live-completed.png`，确认完成回复、正式版入口与导出按钮可见。
- 直接查看 `route-first-live-cancelled.png`，确认停止提示、恢复输入和原正式版区域保留。
- `route-first-cancel-checks.json` 记录停止前后accepted_plan哈希一致，并与completed-checks中的正式版哈希相同。
- 导出已点击，但记录明确写明落盘文件未核对；本轮不将“下载文件内容已验证”计为通过。源码下载使用saved.markdown，有正式版边界基础。

首次有用草案与恢复后完整生成是不同指标；目前已经证明草案可早于食宿选择展示，不能据单个案例宣称总规划一定更快。普通完整行程仍主要等待结构化规划返回，本批不是完整逐日／逐字流式产品的全部实现。

## 6. 再次提交的最小门槛

1. 原16项与本轮9项全部满足期望。
2. 问句／保留／冲突语境不能解除锚点或reset；完整图不产出违约正式版。
3. 餐厅主体不能执行酒店set，酒店主体不能执行餐厅set；正确类别继续可修改。
4. 保持293项正式回归、57项旧不变量和已验证的草案先行／恢复路径。
5. 补齐导出落盘文件内容核对，或在最终验收中如实保留该项未验证说明；不能用截图按钮存在替代文件验证。

图片、逐餐编辑、真实导航与多城市仍为后续产品项，本轮不另加新范围。

## 附录：新增9项测试

```bash
cd Backend
PYTHONPATH=.:tests ../.venv/bin/python -m pytest -q -s -o asyncio_mode=auto /tmp/travel-product-iteration-1-round3/test_extra.py
```

断言为期望正确行为；本轮5失败、4通过。

```python
from copy import deepcopy
import pytest
from test_closed_loop import requirements,candidate
from test_route_first import setup,db
from app.graph import anchors,pipeline,research
from app.schemas.planning import AnchorChange,RequestDecision
from app.agents import orchestrator

@pytest.mark.parametrize('text',['取消真实酒店？先别操作，我只是问问','取消真实酒店，但仍然保留真实酒店'])
def test_question_or_conflicting_retention_does_not_release(text):
    old=requirements(required_hotel='真实酒店').model_dump();req=requirements()
    questions=anchors.preserve_anchors(old,req,[AnchorChange(target='hotel',action='clear',name='真实酒店',user_quote='取消真实酒店')],text)
    assert req.required_hotel=='真实酒店'


def test_restaurant_action_cannot_replace_hotel():
    old=requirements(required_hotel='真实酒店',required_restaurants=['原餐厅']).model_dump();req=requirements();text='餐厅换成湖畔饭店'
    anchors.preserve_anchors(old,req,[AnchorChange(target='hotel',action='set',name='湖畔饭店',user_quote=text)],text)
    assert req.required_hotel=='真实酒店'


def test_question_new_trip_does_not_reset():
    old=requirements(required_hotel='真实酒店',required_restaurants=['真实餐厅']).model_dump();req=requirements();text='开始新旅行？不是，继续原来的行程'
    anchors.preserve_anchors(old,req,[],text,'开始新旅行')
    assert req.required_hotel=='真实酒店' and req.required_restaurants==['真实餐厅']

@pytest.mark.parametrize('kind',['clear','replace','new_trip','all_restaurants'])
def test_supported_normal_changes(kind):
    old=requirements(required_hotel='真实酒店',required_restaurants=['真实餐厅甲','真实餐厅乙']).model_dump();req=requirements()
    if kind=='clear':
        text='请取消真实酒店';changes=[AnchorChange(target='hotel',action='clear',name='真实酒店',user_quote=text)];reset=''
    elif kind=='replace':
        text='酒店换成新的酒店';changes=[AnchorChange(target='hotel',action='set',name='新的酒店',user_quote=text)];reset=''
    elif kind=='new_trip':text='开始一趟新的旅行';changes=[];reset=text
    else:text='取消所有指定餐厅';changes=[AnchorChange(target='restaurant',action='clear',name='',user_quote=text)];reset=''
    questions=anchors.preserve_anchors(old,req,changes,text,reset)
    assert not questions
    if kind=='replace':assert req.required_hotel=='新的酒店'
    elif kind=='all_restaurants':assert req.required_hotel=='真实酒店' and not req.required_restaurants
    elif kind=='new_trip':assert not req.required_hotel and not req.required_restaurants
    else:assert not req.required_hotel and req.required_restaurants==old['required_restaurants']

@pytest.mark.asyncio
async def test_question_fragment_cannot_publish_different_hotel(monkeypatch,db):
    setup(monkeypatch,req=requirements(required_hotel='真实酒店'))
    first=await orchestrator.TripOrchestrator().plan_trip('question-release','已订真实酒店别换',interaction_mode='automatic')
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
    out=await orchestrator.TripOrchestrator().plan_trip('question-release','取消真实酒店？先别操作，我只是问问',interaction_mode='automatic')
    print('QUESTION_RELEASE',out['status'],out['requirements']['required_hotel'],(out.get('itinerary') or {}).get('hotel_evidence_id'))
    assert out['status'] not in ('completed','degraded') or out['itinerary']['hotel_evidence_id']=='h1'
```
