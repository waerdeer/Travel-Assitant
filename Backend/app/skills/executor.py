import logging
from typing import Any, Dict, Annotated, TypedDict

from langgraph.graph import StateGraph, START, END

from app.skills.dag import DAGContext, Node, SkillDAG

logger = logging.getLogger("dag")

def merge_step_results(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Reducer for step_results to merge dicts."""
    c = a.copy()
    c.update(b)
    return c

class TravelState(TypedDict):
    city: str
    start_date: str
    end_date: str
    preferences: str
    accommodation: str
    step_results: Annotated[Dict[str, Any], merge_step_results]

class DAGExecutor:
    """基于 LangGraph 的 DAG 执行引擎。"""

    def __init__(self, mcp_client, llm_client):
        self.mcp = mcp_client
        self.llm = llm_client
        self._compiled_graphs = {}

    async def run(self, dag: SkillDAG, context: DAGContext) -> dict:
        logger.info(f"开始执行 LangGraph: {dag.name}")
        
        # 1. 获取或编译图
        graph = self._get_or_compile_graph(dag)
        
        # 2. 初始化全局 State
        initial_state: TravelState = {
            "city": context.city,
            "start_date": context.start_date,
            "end_date": context.end_date,
            "preferences": context.preferences,
            "accommodation": context.accommodation,
            "step_results": {}
        }
        
        # 3. 执行图 (ainvoke 支持完全异步执行)
        final_state = await graph.ainvoke(initial_state)
        
        logger.info(f"执行完毕 LangGraph: {dag.name}")
        
        # 4. 回填至原始 context 以保持对外接口兼容性
        context.step_results = final_state["step_results"]
        return final_state["step_results"]

    def _get_or_compile_graph(self, dag: SkillDAG):
        """编译或从缓存获取 LangGraph"""
        if dag.name in self._compiled_graphs:
            return self._compiled_graphs[dag.name]

        workflow = StateGraph(TravelState)

        # 注册所有节点
        for name, node in dag.nodes.items():
            workflow.add_node(name, self._create_node_func(node))

        # 注册拓扑边
        workflow.add_edge(START, dag.entry)
        for name, node in dag.nodes.items():
            if node.is_terminal or not node.next_nodes:
                workflow.add_edge(name, END)
            else:
                workflow.add_edge(name, node.next_nodes[0])

        compiled = workflow.compile()
        self._compiled_graphs[dag.name] = compiled
        return compiled

    def _create_node_func(self, node: Node):
        """高阶函数：将静态 Node 定义转换为 LangGraph 异步执行节点"""
        async def node_func(state: TravelState) -> dict:
            logger.info(f"正在执行节点: {node.name}")
            prompt = self._build_prompt(node, state)
            tool_schemas = await self._get_tool_schemas(node.tools)
            
            llm_result = await self.llm.chat(prompt=prompt, tools=tool_schemas)

            if not hasattr(llm_result, "tool_calls") or not llm_result.tool_calls:
                return {"step_results": {node.name: llm_result.content}}

            tool_results = []
            for call in llm_result.tool_calls:
                logger.info(f"  -> MCP Tool Call: {call.name}")
                result = await self.mcp.call_tool(
                    server="amap", tool_name=call.name, arguments=call.arguments,
                )
                tool_results.append(result.content)

            combined = tool_results[0] if len(tool_results) == 1 else tool_results
            return {"step_results": {node.name: combined}}

        return node_func

    def _build_prompt(self, node: Node, state: TravelState) -> str:
        parts = [
            node.prompt,
            "",
            f"目的地: {state['city']}",
            f"日期: {state['start_date']} ~ {state['end_date']}",
        ]
        if state.get("preferences"):
            parts.append(f"偏好: {state['preferences']}")
        if state.get("accommodation"):
            parts.append(f"住宿: {state['accommodation']}")
        if state.get("step_results"):
            parts.append(f"已有数据: {', '.join(state['step_results'].keys())}")
        return "\n".join(parts)

    async def _get_tool_schemas(self, tool_names: list[str]) -> list[dict]:
        if not tool_names:
            return []
        all_tools = await self.mcp.list_tools("amap")
        return [
            {
                "type": "function", 
                "function": {
                    "name": t["name"], 
                    "description": t["description"], 
                    "parameters": t["schema"]
                }
            }
            for t in all_tools if t["name"] in tool_names
        ]
