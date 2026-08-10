from app.skills.dag import Node, SkillDAG

FAMILY_DAG = SkillDAG(
    name="亲子游",
    description="适合带娃出行的行程规划，关注安全、轻松节奏与亲子设施",
    keywords=["亲子", "带娃", "孩子", "小朋友", "儿童", "家庭"],
    entry="query_weather",
    nodes={
        "query_weather": Node(
            name="query_weather",
            prompt="查询目的地未来几天天气，记录温度和天气状况，用于判断是否适合户外活动。",
            tools=["amap_maps_weather"],
            next_nodes=["search_attractions"],
        ),
        "search_attractions": Node(
            name="search_attractions",
            prompt="""根据天气和用户偏好搜索景点。

亲子游要求：
- 优先选择儿童友好景点（动物园、博物馆、主题乐园、科技馆）
- 每天景点不超过 2 个
- 排除不适合儿童的场所""",
            tools=["amap_maps_text_search"],
            next_nodes=["verify_attractions"],
        ),
        "verify_attractions": Node(
            name="verify_attractions",
            prompt="""验证搜索到的景点是否适合亲子游。

检查每个景点：
- 是否儿童友好
- 安全性
- 是否有亲子设施（婴儿车租借、儿童卫生间等）

排除不合适的景点。""",
            tools=["amap_maps_search_detail"],
            next_nodes=["search_hotels"],
        ),
        "search_hotels": Node(
            name="search_hotels",
            prompt="""推荐酒店。

亲子游要求：
- 近景点，减少交通时间
- 有亲子设施（婴儿床、儿童乐园）
- 近医疗资源""",
            tools=["amap_maps_text_search"],
            next_nodes=["search_restaurants"],
        ),
        "search_restaurants": Node(
            name="search_restaurants",
            prompt="""推荐餐厅。

亲子游要求：
- 有儿童座椅
- 菜品适合儿童
- 环境安全干净
- 早中晚三餐 + 小食""",
            tools=["amap_maps_text_search"],
            next_nodes=["generate_plan"],
        ),
        "generate_plan": Node(
            name="generate_plan",
            prompt="""综合所有数据生成亲子游行程方案。

要求：
- 每天景点不超过 2 个，预留午休时间
- 包含每日天气、景点、酒店、餐饮
- 预算估算
- 实用建议（儿童用品、代步车、应急预案）""",
            tools=[],
            is_terminal=True,
        ),
    },
)
