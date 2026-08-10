from app.skills.dag import Node, SkillDAG

BUDGET_DAG = SkillDAG(
    name="穷游预算",
    description="预算敏感型行程，优化交通、住宿与门票支出",
    keywords=["穷游", "省钱", "划算", "预算", "经济", "便宜", "低预算"],
    entry="query_weather",
    #定义个字典 存放每个步骤 对应的node
    nodes={
        "query_weather": Node(
            name="query_weather",
            prompt="查询目的地未来几天天气。",
            tools=["amap_maps_weather"],
            next_nodes=["search_attractions"],
        ),
        "search_attractions": Node(
            name="search_attractions",
            prompt="""根据预算约束搜索景点。

穷游要求：
- 优先推荐免费或低门票景点
- 提供省钱技巧（早鸟票、联票、学生优惠）
- 避开旺季和热门收费景点""",
            tools=["amap_maps_text_search"],
            next_nodes=["search_hotels"],
        ),
        "search_hotels": Node(
            name="search_hotels",
            prompt="""推荐住宿。

穷游要求：
- 经济型酒店、青旅、特色民宿
- 估算每晚上限价格
- 提供省钱建议""",
            tools=["amap_maps_text_search"],
            next_nodes=["search_restaurants"],
        ),
        "search_restaurants": Node(
            name="search_restaurants",
            prompt="""推荐餐饮。

穷游要求：
- 本地特色平价小店
- 人均消费低
- 早中晚三餐""",
            tools=["amap_maps_text_search"],
            next_nodes=["generate_plan"],
        ),
        "generate_plan": Node(
            name="generate_plan",
            prompt="""综合数据生成穷游行程方案。

要求：
- 明确总预算区间
- 各项费用明细（交通、住宿、餐饮、门票）
- 省钱技巧汇总""",
            tools=[],
            is_terminal=True,
        ),
    },
)
