"""Legacy ReAct experiments retained for regression comparisons.

The production graph uses pipeline.py, research.py and validation.py. This module
is intentionally not imported by workflow.py; it remains a learning baseline.
"""
from typing import Dict, Any, List
import json
import logging
logger = logging.getLogger('app.graph.nodes')


from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from pydantic import BaseModel, Field, field_validator
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from app.core.coerce import as_text
from app.core.config import settings
from app.graph.state import TripState
from app.graph.tools import (
    INFO_TOOLS,
    BOOKING_TOOLS,
    PLANNER_TOOLS,
    get_weather_and_climate,
    search_travel_inspiration,
    search_hotels,
)

llm = ChatOpenAI(
    api_key=settings.llm_api_key or "offline-test-placeholder",
    base_url=settings.llm_base_url,
    model=settings.llm_model,
    temperature=0.7
)

# ==========================================
# 0. 共享常量：递归上限与工具调用纪律
# ==========================================

# create_react_agent 每完成一轮「模型思考 + 工具执行」消耗 2 个 super-step，
# recursion_limit 限制的是 super-step 总数。旧的 limit=5 只够 2 次工具调用，
# 而且大概率在 agent 还没来得及输出最终文本时就抛 GraphRecursionError ——
# 三个节点每次都会落进 except，全部静默降级。
#
# 取值不是凭感觉：TOOL_POLICY 把单个工具压到 2 次、情报节点最多 3 个工具调用，
# 即 2*3+1 = 7，取 12 留约 70% 余量给模型多轮思考。
REACT_RECURSION_LIMIT = 12

# 三个 agent 原本各写了一段重试指令，措辞还不一致
# （"直到收集到至少 4 个以上" / "自主扩大搜索半径" / "换个宽泛的餐饮词再搜一次"）——
# 这些正是驱动无限重试的燃料：工具返回空时，它们命令模型「继续搜」，
# 而模型无法区分「工具坏了」和「真的没结果」，于是一路重试到撞 limit，
# 降级后拿着空数据幻觉出整份行程单。
#
# 抽成共享常量注入三个 prompt。核心是让「要不要重试」变成对 ok/retryable
# 两个字段的机械判断，而不是模型自己的猜测。
TOOL_POLICY = (
    "【工具调用纪律 —— 必须严格遵守】\n"
    "工具返回的是 JSON 信封，先看 ok 字段再决定下一步：\n"
    "  · ok=true 且 count>0：拿到真实数据，直接使用。\n"
    "  · ok=true 且 count=0：调用成功，但确实没有匹配结果。"
    "最多换一个关键词重试一次；再为空就停止调用该工具。\n"
    "  · ok=false：调用失败。看 error.retryable：\n"
    "      - retryable=false：禁止重试，重试一万次结果也一样。立即停止调用该工具，"
    "改用你自己的常识完成任务，并在最终回复中明确注明「该部分未使用实时数据」。\n"
    "      - retryable=true：这是临时故障。最多换一次参数重试；再失败就停止。\n"
    "同一个工具最多调用 2 次。达到上限后必须停止，不允许继续尝试。\n"
    "【严禁编造】绝对不许写出 items 里没有出现过的酒店名、餐厅名或景点名。"
    "数据不足时宁可少写、宁可说明「未获取到实时数据」，也不许凭空捏造具体名称。"
)


async def _run_react(
    *, tools, sys_prompt: str, state: TripState, kickoff: str, node_name: str
) -> tuple:
    """跑一次 ReAct 子代理，返回 (最终文本, 错误信息 | None, 工具信封列表)。

    三个节点原本各写了一段几乎一样的 try/except Exception —— 这正是
    「三个节点都静默降级」的结构性原因：一份代码只有一个地方要修。

    错误信息不在这里吞掉，而是返回给调用方写进 state 的 error_msg，
    最终由 routes.py 作为 degraded 标志返回前端。
    「UI 完全正常、不报错」是这次事故最恶劣的特性，这一环就是用来消除它的。

    **第三个返回值是这次重构的核心。** 工具返回的本来就是结构化 JSON 信封，
    它们原封不动地躺在 ToolMessage 里。旧实现却让另一个 LLM 把 JSON 转述成
    散文、再从散文里抽回 JSON —— 既慢又有损，还凭空引入了一整类失败
    （实测该端点的 with_structured_output 必然 400，导致景点/酒店数据全被丢弃）。
    直接把信封交给调用方，这条损失链路就不存在了。
    """
    react_agent = create_react_agent(llm, tools=tools, prompt=sys_prompt)
    invoke_input = {
        "messages": state["messages"] + [HumanMessage(content=kickoff)]
    }
    try:
        agent_res = await react_agent.ainvoke(
            invoke_input, {"recursion_limit": REACT_RECURSION_LIMIT}
        )
    except GraphRecursionError as e:
        # 单独 catch：让「循环防护触发」从静默降级变成一条 ERROR 日志。
        logger.error(
            "[%s] 触发递归上限 %d，ReAct 被强制中断: %s",
            node_name,
            REACT_RECURSION_LIMIT,
            e,
        )
        return "", f"{node_name}: 工具调用轮次超过上限（{REACT_RECURSION_LIMIT}），已强制中断", []
    except Exception as e:
        logger.error("[%s] ReAct 执行异常: %s: %s", node_name, type(e).__name__, e, exc_info=True)
        return "", f"{node_name}: {type(e).__name__}: {e}", []

    messages = agent_res["messages"]
    payloads = _collect_tool_payloads(messages)
    # 这条日志是最终验收标准的第 1 条：N 必须 > 0，否则工具链又断了
    logger.info(
        "[%s] ReAct 完成，工具调用 %d 次，解析出信封 %d 个",
        node_name,
        sum(1 for m in messages if isinstance(m, ToolMessage)),
        len(payloads),
    )
    return _last_ai_text(messages), None, payloads


def _last_ai_text(messages: list) -> str:
    """取最后一条 AI 消息的文本。

    刻意不用 messages[-1]：那个位置未必是 AI 消息。planner_node 的返回值会
    直接当成交付给用户的行程单，万一最后一条是 ToolMessage，用户看到的就是
    一段工具的 JSON 信封原文。
    """
    for message in reversed(messages):
        if getattr(message, "type", "") == "ai":
            return message.content or ""
    return ""


def _collect_tool_payloads(messages: list) -> List[dict]:
    """从 ReAct 的消息历史里取出工具返回的 JSON 信封。

    只认四种工具产出的、带 ok 字段的信封（见 app/graph/tools.py 的三态契约）。
    解析不了的消息直接跳过 —— 那是模型的自然语言回复，不是工具结果。

    `tool` 记的是 **LangChain 工具名**，也就是 ToolNode 从 tool_call 里原样
    抄进 ToolMessage.name 的那个名字（`get_weather_and_climate` 等），
    不是 MCP 服务端的工具名（`maps_weather`）。两者必须分清：
    LangGraph 只认前者，而我们真正想区分的东西也只有前者能区分 ——
    `search_travel_inspiration` 和 `search_hotels` 底层调的是同一个
    `maps_text_search`，按 MCP 名过滤会把两个节点的数据源混成一锅。
    """
    payloads: List[dict] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            payload = json.loads(message.content)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and "ok" in payload:
            payloads.append({"tool": getattr(message, "name", ""), **payload})
    return payloads


def _items_from_tool(payloads: List[dict], tool) -> List[dict]:
    """取某个 LangChain 工具返回的 items。

    入参收工具对象本身而不是字符串：名字由 `tool.name` 提供，避免调用方
    手写第二份名字表 —— 手写的那份一旦和 `@tool` 函数名不一致，就会静默
    取到空列表（本函数曾因此返回 0 条：按 MCP 名 "maps_weather" 过滤，
    而消息上记的是 "get_weather_and_climate"）。

    同一个工具可能被调用多次（TOOL_POLICY 允许 2 次），合并所有成功的结果
    并按 id/name 去重：第一次搜窄了、第二次搜宽了，两次的真实结果都该留下。
    失败的信封（ok=false）不贡献 items —— 失败就是失败，不许变成空数据混进来。
    """
    tool_name = getattr(tool, "name", tool)
    merged: List[dict] = []
    seen: set = set()
    for payload in payloads:
        if payload.get("tool") != tool_name or not payload.get("ok"):
            continue
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            key = item.get("id") or item.get("name")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(item)
    return merged


def _tool_failures(payloads: List[dict]) -> List[str]:
    """汇总工具信封里的失败，供 error_msg 使用。"""
    return [
        f"{p.get('tool')}({(p.get('error') or {}).get('code')})"
        for p in payloads
        if not p.get("ok")
    ]


def _format_weather(items: List[dict]) -> str:
    """把天气工具的结构化预报渲染成紧凑文本。

    刻意不调用 LLM 做「总结」：draft_node 和 planner_node 拿到的本来就是
    逐日预报数据，写穿衣建议是它们自己的活。中间加一层 LLM 转述只会引入
    新的失败点，还多花一次调用。
    """
    if not items:
        return ""
    lines = []
    for day in items:
        lines.append(
            "{date}（周{week}）{dayweather}转{nightweather} "
            "{daytemp}~{nighttemp}℃ {daywind}风{daypower}级".format(
                date=day.get("date", ""),
                week=day.get("week", ""),
                dayweather=day.get("dayweather", ""),
                nightweather=day.get("nightweather", ""),
                daytemp=day.get("daytemp", ""),
                nighttemp=day.get("nighttemp", ""),
                daywind=day.get("daywind", ""),
                daypower=day.get("daypower", ""),
            )
        )
    return "\n".join(lines)


def _with_error(state: dict, update: dict, error) -> dict:
    """只在真的出错时写 error_msg；多个节点的失败累积而不是互相覆盖。

    TripState 没给 error_msg 配 reducer（后写覆盖先写），所以「成功」必须
    表现为「不写这个键」，而不是写 None —— 否则后一个成功的节点会把前一个
    节点的错误悄悄抹掉，degraded 标志就永远亮不起来。

    同一件事的另一面：真的失败了也要累积。图是线性往下走的，实测一轮里
    info_agent（景点/天气全空）和 booking_node（酒店全空）都失败了，而
    前端只收到 booking_node 那一条 —— 最先坏掉的那一环反而看不见。
    """
    if not error:
        return update
    previous = state.get("error_msg")
    update["error_msg"] = f"{previous}; {error}" if previous else error
    return update

# ==========================================
# 0. 路由中枢节点 (Router Node) -> 纯 LLM 节点，不变
# ==========================================
class RouterOutput(BaseModel):
    intent: str = Field(description="用户意图分类，仅限以下三种：'new_trip'(全新行程规划), 'modify_hotel'(修改酒店住宿), 'chat'(普通问答或闲聊)")
    city: str = Field(default="", description="若是全新行程，提取城市")
    start_date: str = Field(default="", description="提取开始日期，例如 2026-08-18")
    end_date: str = Field(default="", description="提取结束日期，例如 2026-08-19")
    custom_preferences: str = Field(default="", description="提取游玩或住宿的特殊要求")

    @field_validator("city", "start_date", "end_date", "custom_preferences", mode="before")
    @classmethod
    def _coerce_to_text(cls, v):
        """LLM 可能把 custom_preferences 吐成 {} 或 ["安静","亲子"] 而不是字符串。

        不加这个校验，dict 会一路带到 SQLAlchemy 的 Text 列上炸掉：
            sqlite3.InterfaceError: Error binding parameter 5
        而 persist_turn 是单事务的，一个字段类型不对就整轮回滚 ——
        这就是三张表至今 0 行的根因。
        """
        return as_text(v)


async def router_node(state: TripState) -> Dict[str, Any]:
    """意图识别中枢：分析最新的用户输入，决定走向"""
    logger.info(">>> 🚀 [进入节点] 路由中枢 (router_node)")
    today = datetime.now().strftime("%Y-%m-%d")
    sys_prompt = f"""
    你是一个旅行助理的路由大脑。今天是 {today}。
    请根据用户最新发送的消息，以及之前的聊天记录，判断他的意图：
    1. 如果用户要求规划一个全新的行程，或者更换了城市，分类为 'new_trip'，并提取 city, date 等。
    2. 如果用户是在现有的行程基础上，要求更换酒店/住宿，分类为 'modify_hotel'。
    3. 如果用户只是在问候、致谢，或者问一些无关旅行规划的普通问题，分类为 'chat'。

    之前确定的城市是: {state.get('city', '无')}。

    必须以 json 格式输出，且只输出这一个 json 对象，不要有任何其他文字或代码块标记。
    字段如下（全部为字符串，缺失就填空字符串）：
      intent            —— 必填，只能是 'new_trip' / 'modify_hotel' / 'chat' 三者之一
      city              —— 提取到的城市名
      start_date        —— 开始日期，格式 YYYY-MM-DD
      end_date          —— 结束日期，格式 YYYY-MM-DD
      custom_preferences —— 用户的游玩或住宿偏好，用一句话描述
    """
    # method="json_mode" 是刻意选的：默认的 json_schema 模式在该端点必然返回
    #   400 This response_format type is unavailable now
    # （function_calling 模式也不行：Thinking mode does not support this tool_choice）
    # json_mode 走 response_format={"type":"json_object"}，实测可用。
    # 之前靠 except 兜住这个必然失败的请求，等于每轮都白跑一次 400。
    #
    # 代价必须写清楚：json_mode 只保证「输出是合法 JSON」，**不传 schema**。
    # 上面那段字段说明因此不是可选的文档，而是这个模式下唯一的契约来源
    # —— json_schema 模式里由 RouterOutput 的 Field(description=...) 承担。
    # 而且服务端强制要求 prompt 里出现 "json" 字样，否则直接 400：
    #   Prompt must contain the word 'json' in some form to use
    #   'response_format' of type 'json_object'.
    structured_llm = llm.with_structured_output(RouterOutput, method="json_mode")
    messages = [SystemMessage(content=sys_prompt)] + state["messages"]

    try:
        res = await structured_llm.ainvoke(messages)
    except Exception as e:
        # 结构化输出失败时的降级路径：让 LLM 直接吐 JSON 字符串。
        #
        # 关键：解析结果必须**走同一个 pydantic 模型**。
        # 旧实现用 parsed.get(...) 手工取值，于是 RouterOutput 上的
        # field_validator 完全不生效 —— 两条产出路径的类型契约不一致，
        # 这正是 {} 能一路带进 DB 的原因。收敛成 model_validate 后，
        # 无论走哪条路，类型保证都由同一处提供。
        logger.warning("结构化输出失败，降级为裸 JSON 解析: %s", e)
        fallback_msg = messages + [HumanMessage(content="请务必只输出包含 intent, city, start_date, end_date, custom_preferences 的标准 JSON 字符串，不要带任何其他前缀后缀。")]
        fallback_res = await llm.ainvoke(fallback_msg)
        try:
            content = fallback_res.content
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            res = RouterOutput.model_validate(json.loads(content))
        except Exception as e2:
            logger.error("路由 JSON 解析也失败，降级为 chat: %s", e2)
            res = RouterOutput(intent="chat")

    intent = res.intent
    city = res.city
    start_date = res.start_date
    end_date = res.end_date
    pref = res.custom_preferences

    logger.info(f"<<< ✅ [离开节点] 路由中枢, 意图判定为: {intent}, 提取城市: {city}")
    update_data = {"intent": intent}
    if intent == "new_trip" and city:
        update_data.update({
            "city": city,
            "start_date": start_date or today,
            "end_date": end_date or today,
            "custom_preferences": pref,
            "persona": "通用标准"
        })
    return update_data

# ==========================================
# 0.5 普通闲聊节点 (Chat Node) -> 纯 LLM 节点，不变
# ==========================================
async def chat_node(state: TripState) -> Dict[str, Any]:
    sys_prompt = "你是一个友好的旅行助理，请简短、礼貌地回复用户的闲聊或问题。"
    messages = [SystemMessage(content=sys_prompt)] + state["messages"]
    res = await llm.ainvoke(messages)
    return {
        "messages": [AIMessage(content=res.content)],
        "final_plan_md": res.content
    }

# ==========================================
# 1. 收集情报节点 (Info Agent - ReAct 架构)
# ==========================================
async def info_agent(state: TripState) -> Dict[str, Any]:
    """收集情报：利用 ReAct 代理自主收集足够的情报"""
    logger.info(">>> 🚀 [进入节点] 收集情报 (info_agent)")
    city = state.get("city", "未知城市")

    # 1. 定义 ReAct 代理的系统指令
    #    旧指令写的是「如果第一次搜索结果不理想，请自主更换关键词重新搜索，
    #    直到收集到至少 4 个以上的优质景点」—— 工具返回空时这是在命令模型
    #    无限重试，是幻觉的直接燃料。改为注入统一的 TOOL_POLICY。
    #
    #    也刻意不再要求模型「输出包含所有查到的信息的总结」：数据已经通过
    #    工具信封进入 state，让模型再复述一遍纯属浪费 token，而且复述是有损的。
    agent_sys_prompt = (
        f"你是一个严谨的情报分析师。任务：为去【{city}】的游客收集情报。\n"
        f"游客偏好：{state.get('custom_preferences', '')}。\n"
        f"\n{TOOL_POLICY}\n\n"
        f"执行步骤：\n"
        f"1. 调用天气工具查询近期天气。\n"
        f"2. 调用景点灵感工具搜索适合的景点，关键词用具体的游玩主题。\n"
        f"3. 工具调用完成后，用一句话说明你查了什么即可。\n"
        f"   **不要在回复里罗列查到的数据** —— 工具结果会被系统直接读取，"
        f"你复述一遍既浪费又可能失真。"
    )

    # 2. 创建并驱动 ReAct 子代理
    _final_answer, error, payloads = await _run_react(
        tools=INFO_TOOLS,
        sys_prompt=agent_sys_prompt,
        state=state,
        kickoff="请开始利用工具收集情报。",
        node_name="info_agent",
    )

    # 3. State Out：直接从工具信封取数据。
    #    旧实现在这里再调一次 LLM，让它把散文「提炼」回结构化 ——
    #    而该端点的 with_structured_output 必然 400，于是每次提炼都失败、
    #    每次都把已经拿到手的数据置空。现在数据从 ToolMessage 直接过来，
    #    这条损失链路整个消失了，节点也少了一次 LLM 调用。
    weather_items = _items_from_tool(payloads, get_weather_and_climate)
    inspiration_list = _items_from_tool(payloads, search_travel_inspiration)
    weather_context = _format_weather(weather_items)

    if not weather_items:
        error = error or "info_agent: 天气工具未返回可用数据"
    if not inspiration_list:
        error = error or "info_agent: 景点工具未返回可用数据"
    for failure in _tool_failures(payloads):
        logger.error("[info_agent] 工具失败: %s", failure)

    logger.info(
        "<<< ✅ [离开节点] 收集情报, 景点数: %d, 天气天数: %d",
        len(inspiration_list),
        len(weather_items),
    )
    return _with_error(
        state,
        {
            "weather_context": weather_context,
            "inspiration_list": inspiration_list,
        },
        error,
    )

# ==========================================
# 2. 生成草案节点 (Draft Node) -> 纯推理节点
# ==========================================
async def draft_node(state: TripState) -> Dict[str, Any]:
    logger.info(">>> 🚀 [进入节点] 生成草案 (draft_node)")
    sys_prompt = (
        f"请制定一个每日游玩大纲草案。\n"
        f"城市: {state.get('city')} \n天气: {state.get('weather_context')}\n"
        f"候选景点: {json.dumps(state.get('inspiration_list', []), ensure_ascii=False)}"
    )
    res = await llm.ainvoke([
        SystemMessage(content=sys_prompt),
        HumanMessage(content="请直接输出包含每天大纲的文字版行程草案。")
    ])
    logger.info("<<< ✅ [离开节点] 生成草案")
    return {"rough_itinerary": res.content}

# ==========================================
# 3. 订机票酒店节点 (Booking Node - ReAct 架构)
# ==========================================
async def booking_node(state: TripState) -> Dict[str, Any]:
    logger.info(">>> 🚀 [进入节点] 订机票酒店 (booking_node)")
    city = state.get("city", "未知城市")

    # 草案可能不存在：modify_hotel 直接从路由跳到这里，不经过 draft_node。
    # 旧实现把这个 None 直接拼进 prompt，模型收到的就是「草案/修改要求: None」。
    draft = state.get("rough_itinerary")
    draft_line = f"草案/修改要求: {draft}\n" if draft else "（本次没有草案，请依据用户最新消息判断落脚区域）\n"

    agent_sys_prompt = (
        f"你是一个严谨的后勤预订管家。任务：在【{city}】为用户寻找合适的住宿酒店。\n"
        f"{draft_line}"
        f"用户最新消息: {state['messages'][-1].content}\n"
        f"偏好要求: {state.get('custom_preferences')}\n"
        f"\n{TOOL_POLICY}\n\n"
        f"执行步骤：\n"
        f"1. 根据落脚区域调用搜索酒店工具。\n"
        f"2. 工具调用完成后，用一句话说明你搜了哪个区域即可。\n"
        f"   **不要在回复里罗列酒店名** —— 工具结果会被系统直接读取。"
    )

    _final_answer, error, payloads = await _run_react(
        tools=BOOKING_TOOLS,
        sys_prompt=agent_sys_prompt,
        state=state,
        kickoff="请帮我寻找酒店。",
        node_name="booking_node",
    )

    # 同样直接从工具信封取数（BOOKING_TOOLS 里只有 search_hotels，它走 maps_text_search）。
    confirmed_hotels = _items_from_tool(payloads, search_hotels)
    # confirmed_attractions 在图里没有任何消费方，只被持久化写进 plan_json。
    # 旧的提炼 LLM 会「确认」一批景点，但那批景点没有任何真实来源。
    # 如实沿用情报节点已经查到的候选景点，不凭空产生新的。
    confirmed_attractions = state.get("inspiration_list", [])

    if not confirmed_hotels:
        error = error or "booking_node: 酒店工具未返回可用数据"
    for failure in _tool_failures(payloads):
        logger.error("[booking_node] 工具失败: %s", failure)

    logger.info("<<< ✅ [离开节点] 订机票酒店, 确认酒店数: %d", len(confirmed_hotels))
    return _with_error(
        state,
        {
            "confirmed_hotels": confirmed_hotels,
            "confirmed_attractions": confirmed_attractions,
        },
        error,
    )

# ==========================================
# 4. 排最终行程节点 (Planner Node - ReAct 架构)
# ==========================================
async def planner_node(state: TripState) -> Dict[str, Any]:
    logger.info(">>> 🚀 [进入节点] 排最终行程 (planner_node)")
    city = state.get('city')
    
    confirmed_hotels = state.get("confirmed_hotels", [])
    inspiration_list = state.get("inspiration_list", [])

    agent_sys_prompt = (
        f"你是一个精益求精的旅行编辑，也是交付给用户的最后一关。\n"
        f"你现在掌握以下信息：\n"
        f"城市: {city}\n"
        f"天气: {state.get('weather_context')}\n"
        f"确认酒店: {json.dumps(confirmed_hotels, ensure_ascii=False)}\n"
        f"候选景点: {json.dumps(inspiration_list, ensure_ascii=False)}\n"
        f"行程大纲: {state.get('rough_itinerary')}\n"
        f"\n{TOOL_POLICY}\n\n"
        f"执行步骤：\n"
        f"1. 审视这几天的行程，调用餐厅搜索工具，为游玩地标附近补充午餐和晚餐推荐。\n"
        f"2. 综合所有信息，生成一篇精美、专业、格式清晰的 Markdown 行程单作为最后一条回复。\n"
    )
    # 数据缺口必须在行程单开头显式声明。
    # 这一句是「UI 完全正常、不报错」的最后一道解药：工具链断了的时候，
    # 用户看到的不是一份看不出破绽的幻觉行程，而是一份写明「本次未获取到
    # 实时数据」的通用建议。
    if not confirmed_hotels or not inspiration_list:
        missing = []
        if not confirmed_hotels:
            missing.append("酒店")
        if not inspiration_list:
            missing.append("景点")
        agent_sys_prompt += (
            f"\n【重要】本次未能获取到实时数据：{'、'.join(missing)}。\n"
            f"你必须在行程单的**最开头**用醒目的引用块声明这一点，"
            f"例如「> ⚠️ 本次未能获取实时{'/'.join(missing)}数据，以下为基于通用经验的建议，"
            f"具体名称请以实际查询为准。」\n"
            f"正文里**绝对不许出现任何具体的酒店名、餐厅名或景点名**，只能描述类型和区域。\n"
        )

    final_markdown, error, _payloads = await _run_react(
        tools=PLANNER_TOOLS,
        sys_prompt=agent_sys_prompt,
        state=state,
        kickoff="请开始查漏补缺（搜餐厅），最后交付给我一份完美的 Markdown 行程单。",
        node_name="planner_node",
    )
    if not final_markdown:
        final_markdown = (
            "> ⚠️ 生成行程单时发生错误，本次未能交付完整方案。\n\n"
            "请稍后重试；若反复失败，请检查后端日志中的 `error_msg`。"
        )

    # 记录助手的最终回复到全局上下文，以便多轮对话可见
    logger.info("<<< ✅ [离开节点] 排最终行程")
    return _with_error(
        state,
        {
            "messages": [AIMessage(content=final_markdown)],
            "final_plan_md": final_markdown,
        },
        error,
    )
