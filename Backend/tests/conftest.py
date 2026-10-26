"""测试共用夹具与路径常量。"""

import json
import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# 集成测试会真实调用高德 MCP 与 LLM，消耗额度且依赖网络，默认整目录跳过。
# 显式开启：RUN_INTEGRATION=1 pytest -m integration
RUN_INTEGRATION = os.environ.get("RUN_INTEGRATION") == "1"


def load_fixture(name: str) -> dict:
    """读取一个从真实高德 MCP 服务器抓下来的响应夹具。

    夹具由 scripts/refresh_fixtures.py 生成，不要手工编辑。
    """
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def fixture():
    return load_fixture


def pytest_collection_modifyitems(config, items):
    """门控 integration 用例。

    刻意放在顶层 conftest：pytest 把每个 conftest.py 都按顶层模块名导入，
    在 tests/integration/ 下再放一个 conftest.py 会遮蔽这一个
    （`from conftest import load_fixture` 会解析到错误的模块）。
    而顶层 conftest 的 collect hook 本来就能看到全部用例，没必要分家。
    """
    if RUN_INTEGRATION:
        return
    skip = pytest.mark.skip(reason="集成测试需显式开启：RUN_INTEGRATION=1")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
