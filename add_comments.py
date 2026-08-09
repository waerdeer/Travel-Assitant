import os

comments = {
    "Backend/app/core/config.py": "全局配置文件，加载环境变量并管理基础配置信息。",
    "Backend/app/core/llm.py": "大语言模型（LLM）客户端封装，负责处理和模型 API 的交互。",
    "Backend/app/core/exceptions.py": "自定义异常类定义，用于规范化处理项目中出现的各类错误。",
    "Backend/app/tools/amap.py": "外部工具：封装高德地图 API，提供真实的天气、地理位置和交通数据检索。",
    "Backend/app/agents/base.py": "智能体基类（BaseAgent），定义所有智能体的标准输入/输出契约及核心执行接口。",
    "Backend/app/agents/orchestrator.py": "核心编排器（中央大脑），负责意图识别、工作流调度及多 Agent 协同分发。",
    "Backend/app/agents/executors/planner.py": "行程统筹规划 Agent，负责汇总各个子 Agent 的数据，生成最终按天划分的旅游日程表。",
    "Backend/app/agents/executors/weather.py": "天气查询 Agent，负责基于目的地和出行时间调用工具获取气象信息。",
    "Backend/app/agents/executors/attraction.py": "景点检索 Agent，负责根据用户的偏好和位置信息，筛选最合适的旅游景点。",
    "Backend/app/agents/executors/hotel.py": "住宿推荐 Agent，负责根据预算和景点位置，寻找合适的住宿方案。",
    "Backend/app/agents/prompts/planner.py": "统筹规划 Agent 的提示词（Prompt）模板。",
    "Backend/app/agents/prompts/weather.py": "天气查询 Agent 的提示词（Prompt）模板。",
    "Backend/app/agents/prompts/attraction.py": "景点检索 Agent 的提示词（Prompt）模板。",
    "Backend/app/agents/prompts/hotel.py": "住宿推荐 Agent 的提示词（Prompt）模板。",
    "Backend/app/mcp/registry.py": "MCP (Model Context Protocol) 注册表，负责管理和注册项目中接入的各种 MCP Server。",
    "Backend/app/mcp/client.py": "MCP 客户端，用于和底层的 MCP 服务进行标准化通信和工具调用。",
    "Backend/app/schemas/Budget.py": "数据实体：定义预算相关的结构化数据类型。",
    "Backend/app/schemas/Meal.py": "数据实体：定义餐饮、美食相关的结构化数据类型。",
    "Backend/app/schemas/Weather.py": "数据实体：定义气象和天气状况的结构化数据类型。",
    "Backend/app/schemas/Dayplan.py": "数据实体：定义单日行程规划的结构化数据类型。",
    "Backend/app/schemas/Location.py": "数据实体：定义地理位置和坐标相关的结构化数据类型。",
    "Backend/app/schemas/Attraction.py": "数据实体：定义旅游景点的结构化数据类型。",
    "Backend/app/schemas/Tripplan.py": "数据实体：定义整个行程安排的顶层结构化数据类型。",
    "Backend/app/schemas/Hotel.py": "数据实体：定义住宿和酒店的结构化数据类型。",
    "Backend/app/working_pipeline.py": "MVP 工作流入口（原型），实现了基于固定顺序（景点->天气->酒店->汇总）的链式规划管道。",
    "Backend/app/prompts/PlannerAgent.py": "(旧版/原型) 统筹规划 Agent 的提示词模板。",
    "Backend/app/prompts/WeatherQueryAgent.py": "(旧版/原型) 天气查询 Agent 的提示词模板。",
    "Backend/app/prompts/AttractionSearchAgent.py": "(旧版/原型) 景点检索 Agent 的提示词模板。",
    "Backend/app/prompts/HotelAgent.py": "(旧版/原型) 住宿推荐 Agent 的提示词模板。",
    "Backend/app/skills/intent_router.py": "意图路由模块，负责分析用户输入，并分配给对应的专业领域 Skill 进行处理。",
    "Backend/app/skills/registry.py": "技能注册表，管理和索引所有可用的专家技能（Skills）。",
    "Backend/app/skills/budget.py": "专家技能：穷游/预算控制，包含预算敏感型用户的特定处理逻辑。",
    "Backend/app/skills/family.py": "专家技能：亲子游，包含带小孩家庭出游的特定处理逻辑（如游乐场、轻松行程）。",
    "Backend/app/skills/food.py": "专家技能：美食游，包含寻找当地特色美食和打卡餐厅的特定处理逻辑。",
    "Backend/app/skills/general.py": "专家技能：常规游，处理普通的、没有特殊偏好的旅行请求。",
    "Backend/app/skills/base.py": "专家技能基类，定义所有 Skill 的标准接口和抽象方法。"
}

for filepath, desc in comments.items():
    if not os.path.exists(filepath):
        continue
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Check if already commented
    if "模块名称" in content or "功能描述" in content:
        continue

    filename = os.path.basename(filepath)
    comment_block = f'''"""
=====================================================================
模块名称: {filename}
功能描述: {desc}
=====================================================================
"""\n\n'''

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(comment_block + content)

print("Comments added successfully.")
