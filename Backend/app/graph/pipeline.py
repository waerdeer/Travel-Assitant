"""Supervisor: understand → research → plan → validate → bounded repair/deliver."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage

from app.core.config import settings
from app.graph.anchors import preserve_anchors, same_city
from app.graph.choices import (
    SCOPE_POLICY_VERSION,
    planner_evidence,
    selected_constraint_issues,
    unavailable_selection,
)
from app.graph.place_policy import unavailable_place
from app.graph.rendering import render_plan
from app.graph.research import fresh_evidence, model_evidence
from app.graph.schedule import needs_attractions, preserve_schedule, schedules
from app.graph.validation import requirement_problems, validate_itinerary
from app.schemas.planning import (
    Evidence,
    HotelRevision,
    Itinerary,
    RequestDecision,
    Requirements,
    ValidationIssue,
    ValidationReport,
)
from app.services.model_gateway import ask_json


def add_usage(state: dict, usage: dict) -> dict:
    metrics = dict(state.get("metrics", {}))
    for key in ("model_calls", "input_tokens", "output_tokens"):
        metrics[key] = metrics.get(key, 0) + usage.get(key, 0)
    return metrics


def accepted_plan_summary(state: dict) -> dict | None:
    """Ground follow-up answers in the accepted version, including its limits.

    Current requirements/validation may belong to a failed edit. They must not
    be described as facts about the last successfully saved itinerary.
    """
    accepted = state.get("accepted_plan") or {}
    itinerary = accepted.get("itinerary")
    if not itinerary:
        return None
    places = {e["evidence_id"]: e["data"].get("name") for e in accepted.get("evidence", [])}
    return {
        "requirements": accepted.get("requirements", {}),
        "days": [
            {
                "date": day["date"],
                "theme": day["theme"],
                "places": [places.get(stop["evidence_id"]) for stop in day["stops"]],
            }
            for day in itinerary.get("days", [])
        ],
        "hotel_candidate": places.get(itinerary.get("hotel_evidence_id")),
        "cost_estimates": itinerary.get("costs", {}),
        "validation": accepted.get("validation", {}),
        "limitations": [
            "费用为估算，未查询实时票价或房价；酒店未预订",
            "未核实营业时间、预约余量及真实导航，不能保证可直接出行",
            "天气仅在证据覆盖对应日期时有效",
        ],
    }


async def understand(state: dict) -> dict:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    decision, usage = await ask_json(
        RequestDecision,
        "你是单城市国内旅行规划的主控。根据最新输入和已有需求识别意图，并返回完整的 requirements。"
        "用户只给出北疆、川西等区域，或多个城市/相距很远的景区时，必须填写 scope_clarification，"
        "解释目前只能规划一个集中游玩区域，请其选定一个目的地，或拆成分段行程。不得自行把北疆替换成阿勒泰。"
        "集中区域必须适配单住宿点、景点与住宿约30公里内的市内规划；阿勒泰—布尔津—喀纳斯—禾木、整个伊犁河谷都不是一个集中区域。"
        "澄清示例可用乌鲁木齐市区、伊宁市区或禾木村内；不能在澄清中承诺多城串联和跨景区线路。"
        "多日请求也不能靠反复游玩同一景点凑满天数，必要时请用户缩短该段或分段。"
        "只有用户已明确选择单个城市/集中景区范围时才清空 scope_clarification；后续继续、重试、换候选不代表同意缩小区域。"
        "已有行程下换酒店是 modify_hotel，调整节奏/日期/预算/景点是 modify_itinerary。"
        "补充缺失信息继续原需求。用户明确开始新旅行才 new_trip。问候/普通知识问答是 chat，reply 简短回答。"
        "问答涉及既有行程时，以 accepted_plan_summary 为准，区分已保存方案与失败修改。"
        "通过程序约束校验不代表实地可执行；不得声称可直接使用、已预订、已核实实时价格或营业时间。"
        "被问到是否可以出发或方案是否可靠时，说明仍需核实的具体事项；普通问候无需重复提醒。"
        "更换城市时清空未重新提供的旧日期、偏好、预算。不要捏造未提供的日期或预算。"
        "日期一律 YYYY-MM-DD，相对日期依据今天；明确 N 天和出发日期时推算返程日期。"
        "用户明确抵达/离开城市时刻分别填arrival_time/departure_time为HH:MM，未知留null；不要把景点预约或用餐时刻当作抵离。接驳arrival_buffer_minutes默认60、departure_buffer_minutes默认90是假设，用户明确留白时才调整。rest_dates只填用户明确整天休息/只入住不观光的日期，不能自行添加。改返程时刻属于modify_itinerary。后续保留未改变的时刻与休息日期，明确新旅行才重置。"
        "用户明确取消抵达/返程时间限制或休息日时，schedule_releases填写target、rest_date（仅取消特定休息日时填日期，空为全部）、user_quote本轮连续原文。疑问、假设、否定不取消。"
        "budget_per_person 指全程人均人民币，不含往返大交通；若给多人总预算需除以人数。"
        "duration_days 只在用户明确天数时填写；已改日期应同步更新天数。"
        "attraction_queries 提供 1–2 个简洁可检索的游玩主题，hotel_area 提供住宿区域，food_query 提供菜系。"
        "为了提供可比较的候选，food_queries 提供2–3个不同餐饮方向的简短查询（如本地菜、地方小吃），"
        "地方小吃、特色面馆等泛称尽量改为该城市具体的菜品或品类查询，避免多个方向搜出同类面馆；不要发明店名。"
        "hotel_profiles 提供1–2个适合预算和偏好的住宿类型。用户明确只要某类则只检索该类。"
        "required_hotel仅填写用户明确已订/必须使用的完整酒店名；required_restaurants仅填写明确必去/已预约餐厅，至少安排一次且不限制其他餐厅。"
        "普通喜欢、感兴趣、看起来不错但不必去都是软偏好，不能填入上述明确约束。未被用户取消的明确约束后续保持，换城市时清空。"
        "同城后续输入的明确约束是保留式更新。只有用户明确要另一趟独立新旅行时才填anchor_reset_quote为本轮连续原文；重新规划、改节奏不算另一次旅行。用户明确取消或替换旧指定地点时，必须填写anchor_changes，target为hotel或restaurant，action为set或clear，name为涉及店名（clear空名表示取消该类全部指定），user_quote必须是本轮连续原文；替换先clear旧再set新。只改节奏、预算、日期、口味时不得生成取消补丁。用户主动要求比较/挑选住宿或餐饮时填写choice_review对应类别。reservation_notes保留明确预约时间原文；本版仅保证地点保留，预约时刻尚未校验，不得声称已满足。"
        "所有查询必须遵守用户明确的饮食禁忌，不为多样性引入不符合要求的菜系或住宿档次。"
        "用户要求更新或换一批候选时用 modify_itinerary，并刷新要求的 hotel/restaurant 类别。"
        "must_visit/avoid_places 只填写用户明确必去/排除的具体地点，兴趣主题放 preferences。"
        "refresh_categories 决定本轮需重新检索哪些证据：只改节奏或日期时复用地点，不重新搜；"
        "换酒店只刷新 hotel；改变游玩主题刷新 attraction；改变饮食要求刷新 restaurant。"
        "preferences 保留兴趣主题和饮食住宿要求，不要把节奏改动混入原偏好字符串。"
        "不要把预算、修饰语和整个句子堆进检索词。城市保留标准名称。",
        {
            "today": today,
            "previous_requirements": state.get("requirements", {}),
            "has_itinerary": bool(state.get("accepted_plan") or state.get("itinerary")),
            "accepted_plan_summary": accepted_plan_summary(state),
            "previous_status": state.get("status"),
            "pending_choice": state.get("pending_choice"),
            "conversation": [
                {"role": m.type, "text": str(m.content)[-2500:]} for m in state["messages"][-8:]
            ],
        },
    )
    req, old_req, intent = (
        decision.requirements,
        state.get("requirements", {}),
        decision.intent,
    )
    if same_city(old_req.get("city", ""), req.city):
        req.city = old_req["city"]
    anchor_questions = preserve_anchors(
        old_req,
        req,
        decision.anchor_changes,
        str(state["messages"][-1].content),
        decision.anchor_reset_quote,
    )
    if intent == "modify_hotel" and any(
        old_req.get(key) != getattr(req, key) for key in ("city", "start_date", "end_date")
    ):
        intent = "modify_itinerary"
    if intent == "chat":
        return {
            "intent": intent,
            "reply": decision.reply or "告诉我目的地和日期，我们一起规划旅程。",
            "status": "awaiting_choice" if state.get("pending_choice") else "chat",
            "validation": {},
            "metrics": add_usage(state, usage),
            "trace": state.get("trace", [])
            + [{"stage": "understand", "summary": "识别为普通问答，无需调用旅行工具"}],
        }
    if req.start_date and not req.end_date and req.duration_days:
        try:
            req.end_date = (
                date.fromisoformat(req.start_date) + timedelta(days=req.duration_days - 1)
            ).isoformat()
        except ValueError:
            pass
    changed_city = bool(old_req.get("city") and req.city != old_req["city"])
    fresh_start = changed_city or (
        intent == "new_trip" and state.get("status") != "awaiting_clarification"
    )
    anchor_questions += preserve_schedule(
        old_req,
        req,
        fresh=fresh_start,
        releases=decision.schedule_releases,
        text=str(state["messages"][-1].content),
    )
    if intent == "modify_hotel" and any(
        getattr(Requirements.model_validate(old_req), key) != getattr(req, key)
        for key in (
            "arrival_time",
            "departure_time",
            "arrival_buffer_minutes",
            "departure_buffer_minutes",
            "rest_dates",
        )
    ):
        intent = "modify_itinerary"
    evidence = (
        []
        if fresh_start
        else fresh_evidence(state.get("evidence", []), req.city, include_unavailable=True)
    )
    if intent == "modify_hotel":
        evidence = [e for e in evidence if e["category"] != "hotel" or unavailable_place(e["data"])]
    refresh = set(decision.refresh_categories)
    if intent == "modify_hotel":
        refresh.add("hotel")
    if old_req.get("must_visit", []) != req.must_visit:
        refresh.add("attraction")
    evidence = [e for e in evidence if e["category"] not in refresh or unavailable_place(e["data"])]
    selected = {} if fresh_start else dict(state.get("selected_options", {}))
    review_categories = (
        ["hotel", "restaurant"] if fresh_start or not state.get("choice_confirmed") else []
    )
    for category, key in (
        ("hotel", "hotel_evidence_id"),
        ("restaurant", "restaurant_evidence_ids"),
    ):
        if category in refresh:
            selected.pop(key, None)
            if category not in review_categories:
                review_categories.append(category)
    if req.start_date and req.start_date == req.end_date:
        selected.pop("hotel_evidence_id", None)
        evidence = [e for e in evidence if e["category"] != "hotel"]
        review_categories = [category for category in review_categories if category != "hotel"]
    problems = requirement_problems(req) + anchor_questions
    if decision.scope_clarification:
        # The scope question already asks for a destination; avoid asking twice.
        problems = [p for p in problems if p != "想去哪个国内城市？第一版支持单城市旅行。"]
        problems.insert(0, decision.scope_clarification)
    trace = state.get("trace", []) + [
        {
            "stage": "understand",
            "intent": intent,
            "summary": "需要补充关键信息" if problems else "需求完整，准备检索证据",
            "reused_evidence": len(evidence),
        }
    ]
    return {
        "intent": intent,
        "scope_policy_version": SCOPE_POLICY_VERSION,
        "spatial_repair_no_progress": False,
        "pending_choice": None,
        "route_draft": None,
        "requested_review_categories": {
            "none": [],
            "hotel": ["hotel"],
            "restaurant": ["restaurant"],
            "both": ["hotel", "restaurant"],
        }[decision.choice_review],
        "preferred_options": {} if fresh_start else state.get("preferred_options", {}),
        "selected_options": selected,
        "review_categories": review_categories,
        "choice_confirmed": not bool(review_categories),
        "requirements": req.model_dump(),
        "decision": decision.model_dump(),
        "city": req.city,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "custom_preferences": req.preferences,
        "persona": req.pace,
        "evidence": evidence,
        "missing_requirements": problems,
        "status": "awaiting_clarification" if problems else "planning",
        "reply": f"已记下：{req.city or '目的地待定'}"
        + (f" · {req.duration_days} 天" if req.duration_days else "")
        + "。\n开始规划前，还需要确认：\n"
        + "\n".join(f"- {p}" for p in problems)
        if problems
        else "",
        "previous_itinerary": None
        if fresh_start
        else state.get("accepted_plan", {}).get("itinerary", state.get("itinerary")),
        "previous_plan_md": "" if fresh_start else state.get("final_plan_md", ""),
        "accepted_plan": {} if fresh_start else state.get("accepted_plan", {}),
        "itinerary": None,
        "final_plan_md": "",
        "validation": {},
        "metrics": add_usage(state, usage),
        "trace": trace,
    }


async def plan(state: dict) -> dict:
    count = state.get("repair_count", 0)
    if selected_constraint_issues(state):
        return unavailable_selection(state)
    if needs_attractions(Requirements.model_validate(state["requirements"])) and not any(
        e["category"] == "attraction" for e in state.get("evidence", [])
    ):
        return {
            "itinerary": None,
            "status": "blocked",
            "reply": "未能获取可用景点数据，本次无法生成有来源的行程。请稍后重试或调整游玩主题。",
            "trace": state.get("trace", [])
            + [{"stage": "plan", "summary": "缺少景点证据，停止生成具体地点行程"}],
        }
    try:
        if state.get("intent") == "modify_hotel" and state.get("previous_itinerary"):
            revision, usage = await ask_json(
                HotelRevision,
                "仅修改住宿，其他日程和费用保持不变。从 hotel 证据中选择符合最新要求的候选酒店 ID。"
                "accommodation 是全程人均住宿估算，非实时房价；basis 说明新住宿估算及保留的其他费用。"
                "总预算需扣除原有餐饮、交通、门票。有校验反馈时修正住宿，不得编造酒店 ID。"
                "preferred_options为软偏好，地理和预算可行时优先考虑；明确required_hotel必须保留。",
                {
                    "requirements": state["requirements"],
                    "preferred_options": state.get("preferred_options", {}),
                    "hotels": model_evidence(
                        [e for e in planner_evidence(state) if e["category"] == "hotel"]
                    ),
                    "previous_itinerary": state["previous_itinerary"],
                    "latest_request": str(state["messages"][-1].content),
                    "validation_feedback": state.get("validation", {}),
                },
            )
            previous = state["previous_itinerary"]
            itinerary = Itinerary.model_validate(
                {
                    **previous,
                    "hotel_evidence_id": revision.hotel_evidence_id,
                    "costs": {
                        **previous["costs"],
                        "accommodation": revision.accommodation,
                        "basis": revision.basis,
                    },
                }
            )
        else:
            itinerary, usage = await ask_json(
                Itinerary,
                "你是旅行规划师。仅用 evidence 中的地点，通过 evidence_id 安排行程，不得发明 ID。"
                "必须完整覆盖日期，普通游玩日至少一个景点；景点不可重复。daily_schedule是程序计算的硬约束，全部活动和自由用餐必须在start_minute/end_minute内；接驳留白是假设，不能声称真实导航。rest=true必须不排景点；requires_attraction=false允许空stops、meal_breaks、stay_anchor_evidence_id，theme明确入住休息/返程。普通日不得凭空休息或删日期绕过规则。"
                "08:00–21:00 内安排，每项不少于30分钟，相邻地点至少留15分钟交通，同区域优先。"
                "relaxed 每天最多2景点，balanced 最多3，intensive 最多5。daily_attraction_limit 若更低也必须遵守。"
                "有餐厅证据时每天至少安排一顿正餐，可以重复餐厅。"
                "自动安排时，在地理和预算可行的前提下尽量轮换不同餐厅，不要每天机械地重复同一家。"
                "selected_options 是用户明确选择的约束，不得偷偷更换；餐厅只从其所选的候选池安排。"
                "preferred_options是软偏好，尽量考虑但可为路线/预算选择其他有效证据；required_hotel必须保留，required_restaurants至少各安排一次且可安排其他餐厅。"
                "route_draft是主要活动草案，优先沿用；必要修正可调整，不能把草案当已核验路线。预约时刻尚未校验，保留地点并明确提醒用户核对。"
                "当context.service_mode=browse，输出service_mode=browse。未指定的酒店/餐厅不必选具体门店，即使证据里有候选也不必使用。"
                "browse模式普通游玩日每天至少一顿实际餐厅或meal_breaks自由用餐留白。meal_breaks含同日景点anchor_evidence_id、start_time/end_time，不虚构店名；用餐至少30分钟，和活动不重叠，前后交通留白足够。"
                "browse模式普通游玩日的非返程日必须提供stay_anchor_evidence_id引用该日真实景点，表示建议住宿检索区域，不是酒店也不代表已预订。空抵离/休息日没有景点时住宿区域待定，保留住宿费用，不造景点或借其他天的引用凑住宿区域。"
                "只有明确required_hotel或selected_options才必须选指定酒店，required_restaurants仍至少安排一次。specific模式多日且有酒店证据时选酒店。"
                "费用是全程人均人民币估算（不含往返大交通），须含餐饮、市内交通、多日住宿。"
                "无实时价格，basis 明确住宿单价×晚数÷人数、餐饮日均×天数等估算假设。"
                "总费用不可超过预算，节约时也不得假设住宿餐饮交通免费。"
                "不要把近期天气当未来旅行日期预报；未核实营业时间和票价须提示。"
                "note/theme/suggestions 中不得新增证据外具体地点或声称已核实价格。"
                "修改请求尽量保留不受影响的安排。若有 validation_feedback，优先修复其中的 error。",
                {
                    "service_mode": "browse"
                    if state.get("planning_strategy") == "route_first"
                    and state.get("interaction_mode") == "automatic"
                    else "specific",
                    "requirements": state["requirements"],
                    "daily_schedule": schedules(Requirements.model_validate(state["requirements"])),
                    "evidence": model_evidence(planner_evidence(state)),
                    "selected_options": state.get("selected_options", {}),
                    "preferred_options": state.get("preferred_options", {}),
                    "route_draft": {
                        key: value
                        for key, value in (state.get("route_draft") or {}).items()
                        if key != "evidence"
                    },
                    "previous_itinerary": state.get("previous_itinerary"),
                    "intent": state.get("intent"),
                    "latest_request": str(state["messages"][-1].content),
                    "current_candidate": state.get("itinerary"),
                    "validation_feedback": state.get("validation", {}),
                },
            )
        if (
            state.get("planning_strategy") == "route_first"
            and state.get("interaction_mode") == "automatic"
        ):
            itinerary.service_mode = "browse"
        return {
            "itinerary": itinerary.model_dump(mode="json"),
            "repair_count": count + 1,
            "metrics": add_usage(state, usage),
            "trace": state.get("trace", [])
            + [
                {
                    "stage": "repair" if count else "plan",
                    "attempt": count + 1,
                    "summary": "根据校验反馈修正行程" if count else "生成引用证据的结构化行程",
                }
            ],
        }
    except Exception as exc:
        error_code = getattr(exc, "code", type(exc).__name__)
        return {
            "status": "failed",
            "metrics": add_usage(state, getattr(exc, "usage", {})),
            "itinerary": None,
            "error_msg": f"规划模型调用失败：{error_code}",
            "reply": "生成行程时模型服务未能返回有效结果，请稍后重试。",
            "trace": state.get("trace", [])
            + [{"stage": "plan", "status": "failed", "error_code": error_code}],
        }


async def validate(state: dict) -> dict:
    report = validate_itinerary(
        Itinerary.model_validate(state["itinerary"]),
        Requirements.model_validate(state["requirements"]),
        [Evidence.model_validate(e) for e in planner_evidence(state)],
    )
    report.issues.extend(selected_constraint_issues(state, state["itinerary"]))
    if state["requirements"].get("reservation_notes"):
        report.issues.append(
            ValidationIssue(
                code="reservation_time_unverified",
                severity="warning",
                message="已保留指定地点，但预约时刻尚未经过结构化校验，请核对行程时段与原预约。",
            )
        )
        report.unverified_checks.append("预约时刻")
    report.passed = not any(issue.severity == "error" for issue in report.issues)
    return {
        "validation": report.model_dump(),
        "trace": state.get("trace", [])
        + [
            {
                "stage": "validate",
                "passed": report.passed,
                "attempt": state["repair_count"],
                "errors": [i.code for i in report.issues if i.severity == "error"],
                "issues": [i.model_dump() for i in report.issues],
                "summary": "约束检查通过" if report.passed else "发现约束冲突，准备修正",
            }
        ],
    }


def after_understand(state: dict) -> str:
    return (
        "deliver"
        if state.get("intent") == "chat" or state.get("status") == "awaiting_clarification"
        else "research"
    )


def after_plan(state: dict) -> str:
    return "validate" if state.get("itinerary") else "deliver"


def after_validate(state: dict) -> str:
    if (
        state["validation"]["passed"]
        or state.get("repair_count", 0) >= settings.max_plan_repairs + 1
    ):
        return "deliver"
    codes = {i["code"] for i in state["validation"]["issues"] if i["severity"] == "error"}
    if (
        state.get("interaction_mode") != "automatic"
        and codes & {"long_transfer", "distant_hotel"}
        and state.get("research_round", 0) < 2
        and state.get("tool_calls", 0) < settings.max_tool_calls
    ):
        return "research"
    missing = any(i["code"] == "must_visit_missing" for i in state["validation"]["issues"])
    if (
        missing
        and state.get("research_round", 0) < 2
        and state.get("tool_calls", 0) < settings.max_tool_calls
    ):
        names = [
            e["data"].get("name", "")
            for e in state.get("evidence", [])
            if e["category"] == "attraction"
        ]
        if any(
            not any(place in name for name in names)
            for place in state["requirements"].get("must_visit", [])
        ):
            return "research"
    return "plan"


async def deliver(state: dict) -> dict:
    status, reply, md = (
        state.get("status", "failed"),
        state.get("reply", ""),
        state.get("final_plan_md", ""),
    )
    if (
        state.get("intent") != "chat"
        and state.get("validation", {}).get("passed")
        and state.get("itinerary")
    ):
        report = ValidationReport.model_validate(state["validation"])
        md = render_plan(
            Itinerary.model_validate(state["itinerary"]),
            Requirements.model_validate(state["requirements"]),
            [Evidence.model_validate(e) for e in state["evidence"]],
            report,
        )
        status = "degraded" if state.get("error_msg") else "completed"
        reply = f"已完成{state['requirements']['city']}行程，并通过 {len(report.checks)} 类约束检查。费用为估算，出行前仍需核实营业与预订信息。"
        if state["requirements"].get("reservation_notes"):
            reply += "指定地点已保留，预约时刻仍需你核对。"
    elif (
        state.get("intent") != "chat"
        and state.get("validation")
        and not state["validation"].get("passed")
    ):
        status = "needs_revision"
        errors = [i["message"] for i in state["validation"]["issues"] if i["severity"] == "error"]
        reply = "经过有限修正，仍有以下约束未满足，本次不交付为已完成行程：\n" + "\n".join(
            f"- {e}" for e in errors
        )
        md = ""
    update = {
        "status": status,
        "reply": reply,
        "final_plan_md": md,
        "messages": [AIMessage(content=reply)],
        "trace": state.get("trace", [])
        + [
            {
                "stage": "deliver",
                "status": status,
                "summary": "交付已校验行程" if md and status != "chat" else "返回说明与下一步",
            }
        ],
    }
    if status in ("completed", "degraded"):
        update["route_draft"] = None
        update["accepted_plan"] = {
            "itinerary": state["itinerary"],
            "requirements": state["requirements"],
            "evidence": state["evidence"],
            "validation": state["validation"],
            "plan_md": md,
        }
    return update
