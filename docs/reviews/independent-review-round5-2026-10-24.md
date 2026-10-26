# 第五轮独立对抗验收

日期：2026-10-24。结论：**本批缺陷修复验收通过，限定于下述已覆盖路径；未发现新的阻断缺陷。**

第四轮 R4-1（P1）与 R4-2（P2）均已通过独立重放；前几轮的候选恢复、范围策略、无进展拒绝、事实保留和正式版本保护没有在本轮覆盖中回归。此结论不等于产品整体成熟、实时营业已核实或可以直接公开上线。

## 1. 本轮实际结果

| 检查 | 实际结果 |
| --- | --- |
| 后端完整正式测试 | **267 passed、11 skipped，1.87秒** |
| 第二轮34项＋第三轮组合＋第四轮4项独立重放 | **39 passed，0.61秒** |
| 第五轮独立边界检查 | **18 passed，0.52秒** |
| 前端 lint/build | 通过 |

独立重放使用上一轮已有 `/tmp` 测试，保留正确行为断言；详情诊断日志沿用第三轮已做的 None 安全读取，没有弱化阻断、替代或状态保留要求。

本轮继续使用真实生产图／函数及先前独立HTTP／SQLite用例，外部模型与地图返回为确定性替身，时间边界使用测试时钟。没有访问原用户会话、调用真实外部服务、重启服务或修改业务代码、依赖、既有报告。仅新增本文及 `/tmp` 独立测试；前端构建产生常规生成文件。

上述测试有功能重叠，不能将测试数量相加当成用户样本量、成功率或统计置信度。

## 2. 缺陷逐项复核

| 原问题 | 本轮结论与证据 |
| --- | --- |
| F1 名称／状态过滤遗漏 | 中文字段、明确名称关闭标记和旧候选拒绝重放通过；正常名称负例通过。仍是保守排除，不是营业认证 |
| F2 自动恢复及所选约束失效 | 手动／自动、部分／全部失效、过期、异城、类别不符、有效替代与所选硬约束重放通过 |
| F3 旧范围pending绕过 | 隔离HTTP恢复中，旧版先澄清，当前版本直接恢复；原正式版受保护，重复token拒绝 |
| F4 空周边结果无进展 | 相同条件／选择在恢复后零调用拒绝；时间戳刷新不绕过；HTTP／SSE错误不修改原消息、token和正式版本 |
| R2-1 中文状态字段同义值 | 4种状态在3个既有字段重放通过；完整图不再发布该不可用酒店 |
| R2-2 详情关闭信号丢弃 | 同ID详情的有／无坐标关闭信号保留；错误／缺失ID不污染；正常详情保持坐标补全 |
| R3-1 其他类别检索删除关闭事实 | 常规组合重放通过：关闭酒店事实保留，餐厅修复不能消解住宿失败，无替代则不产出新正式版 |
| R4-1 新关闭事实按旧地点时间过期 | **通过**。初始5小时59分合法→两分钟后新详情关闭→餐厅修复→暂停恢复：关闭事实保留；无替代blocked且原accepted_plan不变；有替代completed并用h2 |
| R4-2 乱序旧关闭覆盖新营业 | **通过**。有效时间双向比较已生效，旧关闭不能覆盖新明确营业；等时冲突保持保守关闭 |

## 3. 新增18项独立检查的范围

针对酒店、餐厅、景点三类事实，分别检查：

1. 原地点检索已七小时，但五分钟前详情确认关闭：事实可保留，仍不可作为候选。
2. 连续多次缺状态的后续检索：保留原可用性时间与原检索时间，不延长关闭事实寿命；其状态来源真正过期后退出有效事实集合。
3. 明确新营业状态：按时间更新，正反顺序及旧记录再次出现均不能覆盖新状态。
4. 未来时间、真正过期和不同城市：不进入当前有效事实集合。
5. 等时字段矛盾（business_status=open、operating_status=已关闭）：两种合并顺序都保持不可用，候选排除。
6. 真正经过 `_normalize_poi()` 的明确营业字段仍能保留并进入合并，不只验证直接手写merge输入。

这些检查均通过。当前 `fact_time` 在事实新鲜度与合并判断中使用同一规则；新关闭信号不会把原始地点检索时间改成当前时间。此处的“明确营业状态可更新”只表示证据规则接受该来源信息，不代表系统独立认证该地点实际营业。

## 4. 未验证项与交付边界

- **未做新增真实地图／模型随机性评估。** 不证明真实高德状态字段覆盖率、自然语言范围判断稳定率、模型推荐质量或时延分布。原北疆输入的历史真实记录与本轮fixture测试必须分开表述。
- **未扩大产品支持范围。** 仍为单城市／集中范围、单住宿点能力；北疆七天环线、多城市交通和多住宿点不在此次通过范围。
- **未全面核验营业。** 详情仍在按需坐标补全链路调用；本轮只保证已取得且身份匹配的明确关闭信号按规则保留处理，不保证所有已有坐标地点均重新查询。
- **未核验实时价格、预约与真实导航。** 保守状态合并及程序校验不等于计划可直接执行。
- **未重新做浏览器人工交互。** 本轮重跑前端静态／构建检查和隔离HTTP用例；浏览器证据仍以先前记录为准，不能宣称覆盖所有设备尺寸和交互组合。
- **仍有产品工作待做。** 具体餐厅提前选择、偏好／必去／预订分层、路线草案渐进交付、地图与局部修改、长行程体验仍按初始产品报告推进。它们未在本批实施，不影响本批既定修复验收结论。

可以结束这批反例修复循环，进入产品流程改进与固定真实任务集评估。今后新增数据来源、并发检索或状态语义时，应保留本批时间、身份、选择和版本隔离回归，避免再次把“不可用事实”混成“缺数据”。

## 附录：第五轮独立边界测试

保存为 `/tmp/travel-independent-review-round5/test_round5_extra.py`，项目根目录执行：

```bash
cd Backend
PYTHONPATH=.:tests ../.venv/bin/python -m pytest -q -o asyncio_mode=auto /tmp/travel-independent-review-round5/test_round5_extra.py
```

此前39项重放代码见第二至四轮报告，本轮未修改其期望。

```python
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import pytest
from test_human_choices import pending_state
from app.graph import research,choices
from app.graph.place_policy import unavailable_place

@pytest.mark.asyncio
@pytest.mark.parametrize('category',['hotel','restaurant','attraction'])
@pytest.mark.parametrize('scenario',['unknown_chain','new_open','future','expired','wrong_city'])
async def test_availability_lifetime_and_status_sequences(category,scenario):
    base=await pending_state();item=deepcopy(next(e for e in base['evidence'] if e['category']==category));now=datetime.now(timezone.utc)
    item['fetched_at']=(now-timedelta(hours=7)).isoformat();signal=now-timedelta(minutes=5)
    item['data'].update(business_status='closed',availability_fetched_at=signal.isoformat(),availability_source='maps_search_detail')
    if scenario=='unknown_chain':
        unknowns=[]
        for seconds in [60,30,0]:
            incoming=deepcopy(item);incoming['fetched_at']=(now-timedelta(seconds=seconds)).isoformat()
            for key in ['business_status','availability_fetched_at','availability_source']:incoming['data'].pop(key,None)
            unknowns.append(incoming)
        result=research.merge_evidence([item,*unknowns])[0]
        assert unavailable_place(result['data']) and research.fact_time(result)==signal
        assert result['fetched_at']==item['fetched_at']
        assert research.fresh_evidence([result],item['city'],include_unavailable=True)
        assert not research.fresh_evidence([result],item['city'])
        result['data']['availability_fetched_at']=(now-timedelta(hours=7)).isoformat()
        assert not research.fresh_evidence([result],item['city'],include_unavailable=True)
    elif scenario=='new_open':
        opened=deepcopy(item);opened['fetched_at']=now.isoformat();opened['data']['business_status']='正常营业'
        for ordered in [[item,opened],[opened,item],[item,opened,item]]:
            result=research.merge_evidence(ordered)[0]
            assert not unavailable_place(result['data']) and research.fact_time(result)==now
            assert research.fresh_evidence([result],item['city'])
    elif scenario=='future':
        item['data']['availability_fetched_at']=(now+timedelta(minutes=5)).isoformat()
        assert not research.fresh_evidence([item],item['city'],include_unavailable=True)
    elif scenario=='expired':
        item['data']['availability_fetched_at']=(now-timedelta(hours=6,seconds=1)).isoformat()
        assert not research.fresh_evidence([item],item['city'],include_unavailable=True)
    else:assert not research.fresh_evidence([item],'另一个城市',include_unavailable=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('order',[False,True])
async def test_equal_time_conflicting_fields_remain_conservatively_unavailable(order):
    base=await pending_state();opened=deepcopy(next(e for e in base['evidence'] if e['category']=='hotel'))
    opened['data']['business_status']='open';closed=deepcopy(opened);closed['data']['operating_status']='已关闭'
    result=research.merge_evidence([opened,closed] if order else [closed,opened])[0]
    assert unavailable_place(result['data'])
    state={**base,'evidence':[result]}
    assert not choices.available_evidence(state)

@pytest.mark.asyncio
async def test_normalization_preserves_new_explicit_open_for_merge():
    from app.graph.tools import _normalize_poi
    base=await pending_state();closed=deepcopy(next(e for e in base['evidence'] if e['category']=='hotel'));now=datetime.now(timezone.utc)
    closed['fetched_at']=(now-timedelta(minutes=5)).isoformat();closed['data']['business_status']='closed'
    opened=deepcopy(closed);opened['fetched_at']=now.isoformat();opened['data']=_normalize_poi({'id':'h1','name':'重新营业的酒店','typecode':'100100','business_status':'正常营业'})
    result=research.merge_evidence([closed,opened])[0]
    assert not unavailable_place(result['data']) and choices.shortlist([result],'hotel',4)
```
