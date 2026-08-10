from app.skills.dag import Node, SkillDAG

GENERAL_DAG = SkillDAG(
    name="通用行程",
    description="标准旅行规划，覆盖大多数行程需求",
    keywords=[],
    entry="query_weather",
    nodes={
        "query_weather": Node(
            name="query_weather",
            prompt="查询目的地未来几天天气，记录温度和天气状况。",
            tools=["amap_maps_weather"],
            next_nodes=["search_attractions"],
        ),
        "search_attractions": Node(
            name="search_attractions",
            prompt="根据用户偏好搜索合适的景点，每天安排 2-3 个。",
            tools=["amap_maps_text_search"],
            next_nodes=["search_hotels"],
        ),
        "search_hotels": Node(
            name="search_hotels",
            prompt="根据景点位置和住宿偏好推荐酒店。",
            tools=["amap_maps_text_search"],
            next_nodes=["search_restaurants"],
        ),
        "search_restaurants": Node(
            name="search_restaurants",
            prompt="推荐早中晚三餐及特色小吃。",
            tools=["amap_maps_text_search"],
            next_nodes=["generate_plan"],
        ),
        "generate_plan": Node(
            name="generate_plan",
            prompt="综合所有数据生成完整行程方案，包含每日景点、酒店、餐饮、天气和预算。",
            tools=[],
            is_terminal=True,
        ),
    },
)
