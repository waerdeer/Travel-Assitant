class TripPlannerError(Exception):
    """行程规划基础异常"""


class AgentExecutionError(TripPlannerError):
    """Agent 执行异常"""


class ToolCallError(TripPlannerError):
    """工具调用异常"""
