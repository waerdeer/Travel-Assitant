import os
import asyncio
from app.graph.workflow import app_graph
from langchain_core.messages import HumanMessage

async def main():
    print("Testing LangGraph tracing...")
    config = {"configurable": {"thread_id": "test_tracing"}}
    state = {"messages": [HumanMessage(content="帮我规划去苏州的2天行程，我要吃松鼠桂鱼")]}
    
    # Run the graph
    await app_graph.ainvoke(state, config)
    print("Done! Check your LangSmith dashboard.")

if __name__ == "__main__":
    asyncio.run(main())
