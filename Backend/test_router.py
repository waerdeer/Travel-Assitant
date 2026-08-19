import asyncio
from app.graph.workflow import app_graph
from langchain_core.messages import HumanMessage

async def main():
    print("Testing intent routing for irrelevant question...")
    config = {"configurable": {"thread_id": "test_routing_name"}}
    
    # 第一次提问：规划杭州
    print("\n--- 第一轮：规划杭州 ---")
    state1 = {"messages": [HumanMessage(content="帮我规划去杭州的行程")]}
    res1 = await app_graph.ainvoke(state1, config)
    print("Intent:", res1.get("intent"))
    print("Final output:", res1.get("final_plan_md")[:50] + "...")

    # 第二次提问：闲聊
    print("\n--- 第二轮：闲聊提问 ---")
    state2 = {"messages": [HumanMessage(content="你知道我叫什么名字吗 还有我的狗")]}
    res2 = await app_graph.ainvoke(state2, config)
    print("Intent:", res2.get("intent"))
    print("Final output:", res2.get("final_plan_md"))

if __name__ == "__main__":
    asyncio.run(main())
