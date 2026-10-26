"""跨层类型收敛工具。

放在 `app.core` 而不是某个具体模块，是因为它**不依赖任何内部模块** ——
既不 import settings，也不 import db，因此可以被任意层引用而不会产生循环导入。
"""

import json
from typing import Any


def as_text(value: Any) -> str:
    """把任意值收敛成可直接写入 Text 列的字符串。

    存在的理由是一次真实事故：
        sqlite3.InterfaceError: Error binding parameter 5 - probably unsupported type.
        [parameters: ('e2e-demo', '上海', ..., '通用标准', {}, 'completed', ...)]

    LLM 在裸 JSON fallback 路径里吐了个 `{}` 当作 custom_preferences，这个 dict
    一路带到 SQLAlchemy，绑定时炸掉。而 persist_turn 是**单事务**的 ——
    一个字段类型不对，整轮回滚，conversations / messages / trips 三张表至今 0 行。

    约定：
      - str 原样返回（含空串）
      - None → ""
      - dict / list → json.dumps(ensure_ascii=False)，保留中文可读性
      - 其他标量 → str()
      - 任何序列化失败都不抛异常，退回 repr() —— 本函数的契约是「永不抛出」，
        因为它的调用点（persist_turn）正是那个不该有能力回滚整个事务的地方。
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return repr(value)
    try:
        return str(value)
    except Exception:
        return repr(value)
