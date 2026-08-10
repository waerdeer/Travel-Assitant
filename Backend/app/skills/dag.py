from dataclasses import dataclass, field


@dataclass
class Node:
    """DAG 中的一个执行步骤。

    每个 Node 代表一次 LLM 调用，包含：
    - prompt: 这一步给 LLM 的指令
    - tools: 这一步可用的 MCP 工具（空列表 = 纯生成，不调工具）
    - next_nodes: 后续节点名（支持分支）
    - is_terminal: 是否终节点
    """

    name: str
    prompt: str
    tools: list[str] = field(default_factory=list)
    next_nodes: list[str] = field(default_factory=list)
    is_terminal: bool = False


@dataclass
class DAGContext:
    """跨节点共享的上下文数据。

    每个 Node 执行后，将结果写入 step_results[node_name]。
    下一个 Node 可以从 step_results 中读取之前的所有数据。
    """

    city: str
    start_date: str
    end_date: str
    preferences: str = ""
    accommodation: str = ""
    step_results: dict = field(default_factory=dict)


@dataclass
class SkillDAG:
    """一个完整的技能有向无环图。

    定义了从入口节点到终节点的完整执行路径。
    不同的 Skill（亲子游/穷游/美食）是不同的 DAG 实例。
    """

    name: str
    description: str
    keywords: list[str]
    nodes: dict[str, Node]
    entry: str
