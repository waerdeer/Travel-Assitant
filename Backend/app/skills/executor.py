import logging
from typing import Any, Optional

from app.skills.dag import DAGContext, Node, SkillDAG

logger = logging.getLogger("dag")


class ToolCall:
    """LLM 返回的工具调用请求。"""

    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = arguments


class StepResult:
    """单步执行结果。"""

    def __init__(self, content: Any = None, tool_calls: list[ToolCall] = None):
        self.content = content
        self.tool_calls = tool_calls or []


class DAGExecutor:
    """DAG 执行引擎：按节点顺序驱动 LLM + MCP 完成任务。"""

    def __init__(self, mcp_client, llm_client):
        self.mcp = mcp_client
        self.llm = llm_client

    async def run(self, dag: SkillDAG, context: DAGContext) -> dict:
        logger.info(f"开始执行: {dag.name}")
        current = dag.entry
        step = 0

        while current:
            node = dag.nodes[current]
            step += 1
            logger.info(f"[{step}/{len(dag.nodes)}] {node.name}")

            step_result = await self._execute_node(node, context)
            context.step_results[node.name] = step_result.content
            current = self._resolve_next(node, step_result)

        logger.info(f"执行完毕: {dag.name}, 共 {step} 步")
        return context.step_results

    async def _execute_node(self, node: Node, context: DAGContext) -> StepResult:
        prompt = self._build_prompt(node, context)
        tool_schemas = await self._get_tool_schemas(node.tools)
        llm_result = await self.llm.chat(prompt=prompt, tools=tool_schemas)

        if not hasattr(llm_result, "tool_calls") or not llm_result.tool_calls:
            return StepResult(content=llm_result.content)

        tool_results = []
        for call in llm_result.tool_calls:
            logger.info(f"  -> {call.name}")
            result = await self.mcp.call_tool(
                server="amap", tool_name=call.name, arguments=call.arguments,
            )
            tool_results.append(result.content)

        combined = tool_results[0] if len(tool_results) == 1 else tool_results
        return StepResult(content=combined)

    def _build_prompt(self, node: Node, context: DAGContext) -> str:
        parts = [
            node.prompt,
            "",
            f"目的地: {context.city}",
            f"日期: {context.start_date} ~ {context.end_date}",
        ]
        if context.preferences:
            parts.append(f"偏好: {context.preferences}")
        if context.accommodation:
            parts.append(f"住宿: {context.accommodation}")
        if context.step_results:
            parts.append(f"已有数据: {', '.join(context.step_results.keys())}")
        return "\n".join(parts)

    async def _get_tool_schemas(self, tool_names: list[str]) -> list[dict]:
        if not tool_names:
            return []
        all_tools = await self.mcp.list_tools("amap")
        return [
            {"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["schema"],
            }}
            for t in all_tools if t["name"] in tool_names
        ]

    def _resolve_next(self, node: Node, result: StepResult) -> Optional[str]:
        if node.is_terminal or not node.next_nodes:
            return None
        return node.next_nodes[0]
