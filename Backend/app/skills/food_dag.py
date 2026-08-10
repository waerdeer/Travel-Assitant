from app.skills.dag import Node, SkillDAG

FOOD_DAG = SkillDAG(
    name="美食攻略",
    description="以美食体验为核心的行程，突出本地特色餐饮",
    keywords=["美食", "吃", "吃货", "米其林", "小吃", "地道", "餐饮"],
    entry="query_weather",
    nodes={
        "query_weather": Node(
            name="query_weather",
            prompt="查询目的地未来几天天气。",
            tools=["amap_maps_weather"],
            next_nodes=["search_attractions"],
        ),
        "search_attractions": Node(
            name="search_attractions",
            prompt="""以美食动线为核心搜索景点和美食聚集区。

美食攻略要求：
- 重点搜索当地美食街、特色小吃聚集区
- 景点围绕美食动线安排，避免频繁跨折返
- 标注每家餐厅的推荐理由和人均消费""",
            tools=["amap_maps_text_search"],
            next_nodes=["search_hotels"],
        ),
        "search_hotels": Node(
            name="search_hotels",
            prompt="""推荐酒店。

美食攻略要求：
- 优先靠近美食聚集区
- 方便夜间觅食""",
            tools=["amap_maps_text_search"],
            next_nodes=["search_restaurants"],
        ),
        "search_restaurants": Node(
            name="search_restaurants",
            prompt="""深度搜索餐厅。

美食攻略要求：
- 三餐类型齐全（早餐/午餐/晚餐/小吃）
- 标注是否需要提前预约
- 提供必吃清单与避坑提示
- 包含本地特色菜系介绍""",
            tools=["amap_maps_text_search"],
            next_nodes=["generate_plan"],
        ),
        "generate_plan": Node(
            name="generate_plan",
            prompt="""综合数据生成美食行程方案。

要求：
- 每天重点安排 2-3 家特色餐厅
- 餐饮占比在预算中单独说明
- 提供必吃清单
- 景点安排围绕美食动线""",
            tools=[],
            is_terminal=True,
        ),
    },
)
