"""设备 Todo 镜像上报测试（spec #30 T1 / #31）：receipt 解析 + 挂钩上报 + per-device FIFO。"""
import asyncio
import contextlib
import json
from types import SimpleNamespace

import pytest
from loguru import logger

from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool
from mcp_services import todo_sync

MAC = "AA:BB:CC:DD:EE:FF"


def make_conn(device_id=MAC):
    return SimpleNamespace(device_id=device_id, logger=logger)


async def drain():
    if todo_sync._report_tasks:
        await asyncio.wait_for(asyncio.gather(*list(todo_sync._report_tasks)), timeout=2)


@pytest.fixture
def _real_sleep(monkeypatch):
    """顶层 conftest 把 asyncio.sleep 换成不 yield 的空操作，FIFO 时序测试需真等待。"""

    async def _real_sleep(seconds):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, __import__("time").sleep, min(seconds, 0.3))

    monkeypatch.setattr(asyncio, "sleep", _real_sleep)


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    for task in list(todo_sync._report_tasks):
        with contextlib.suppress(RuntimeError):
            task.cancel()
    todo_sync._report_tasks.clear()
    todo_sync._locks.clear()


class TestParseReceipt:
    """set_todos receipt 契约：成功 {"ok":true,"todos":[全量]}，item={"text","done"}。"""

    def test_valid_receipt_returns_full_list(self):
        raw = json.dumps({"ok": True, "todos": [
            {"text": "读绘本", "done": False}, {"text": "刷牙", "done": True}]})
        assert todo_sync.parse_receipt(raw) == [
            {"text": "读绘本", "done": False}, {"text": "刷牙", "done": True}]

    def test_failed_or_malformed_receipt_returns_none(self):
        assert todo_sync.parse_receipt(json.dumps({"ok": False, "todos": []})) is None
        assert todo_sync.parse_receipt("not json") is None
        assert todo_sync.parse_receipt(json.dumps([1, 2])) is None
        assert todo_sync.parse_receipt(json.dumps({"ok": True})) is None  # 无 todos
        assert todo_sync.parse_receipt(json.dumps({"ok": True, "todos": "x"})) is None

    def test_non_contract_items_dropped(self):
        raw = json.dumps({"ok": True, "todos": [
            {"text": "读绘本", "done": True},
            {"text": 123, "done": True},  # text 非字符串
            {"text": "刷牙"},             # 缺 done
            "junk",
        ]})
        assert todo_sync.parse_receipt(raw) == [{"text": "读绘本", "done": True}]


class TestReportHook:
    """MCP set_todos 返回路径挂钩：receipt 有效即异步上报全量，旁路绝不影响主流程。"""

    async def test_valid_receipt_reports_full_list(self, monkeypatch):
        reported = []

        async def fake_report(mac, todos):
            reported.append((mac, todos))

        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_report)
        todos = [{"text": "读绘本", "done": False}, {"text": "刷牙", "done": True}]
        todo_sync.on_set_todos_receipt(make_conn(), json.dumps({"ok": True, "todos": todos}))
        await drain()
        assert reported == [(MAC, todos)]

    async def test_invalid_receipt_skips_report(self, monkeypatch):
        called = []

        async def fake_report(mac, todos):
            called.append(mac)

        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_report)
        todo_sync.on_set_todos_receipt(make_conn(), json.dumps({"ok": False, "todos": []}))
        todo_sync.on_set_todos_receipt(make_conn(), "not json")
        await drain()
        assert called == []

    async def test_report_failure_is_silent(self, monkeypatch):
        async def boom(mac, todos):
            raise RuntimeError("api down")

        monkeypatch.setattr("config.manage_api_client.report_todo_list", boom)
        todo_sync.on_set_todos_receipt(make_conn(), json.dumps({"ok": True, "todos": []}))
        await drain()  # 不抛错即通过

    async def test_per_device_fifo_slow_first_report_lands_first(self, monkeypatch, _real_sleep):
        """同一设备两次语音操作：慢的首报持锁期间次报只能排队，落库顺序=操作顺序。"""
        landed = []

        async def fake_report(mac, todos):
            text = todos[0]["text"] if todos else ""
            if text == "读绘本":  # 首报慢（manager-api 抖动）
                await asyncio.sleep(0.2)
            landed.append(text)

        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_report)
        conn = make_conn()
        todo_sync.on_set_todos_receipt(conn, json.dumps({"ok": True, "todos": [{"text": "读绘本", "done": False}]}))
        todo_sync.on_set_todos_receipt(conn, json.dumps({"ok": True, "todos": [{"text": "刷牙", "done": False}]}))
        await drain()
        assert landed == ["读绘本", "刷牙"]


# ───────────────────────── mcp_handler 挂钩接线（真实 call_mcp_tool 路径） ─────────────────────────

class FakeWS:
    """设备端 MCP 响应回环：tools/call 请求立即按预设 receipt 结算 future。"""

    def __init__(self, conn, receipt_text):
        self._conn = conn
        self._receipt = receipt_text

    async def send(self, message):
        m = json.loads(message)
        mc = self._conn.mcp_client
        if m.get("type") == "mcp" and m["payload"].get("method") == "tools/call":
            fut = mc.futures.get(m["payload"]["id"])
            if fut and not fut.done():
                fut.set_result({"content": [{"text": self._receipt}]})


class FakeMCPClient:
    def __init__(self, tools):
        self.tools = {name: {"description": name, "inputSchema": {}} for name in tools}
        self.name_mapping = {}
        self.ready = True
        self.futures = {}

    def has_tool(self, name):
        return name in self.tools

    async def is_ready(self):
        return self.ready

    async def get_next_id(self):
        return len(self.futures) + 1

    async def register_call_result_future(self, tid, future):
        self.futures[tid] = future


def wire_conn(receipt_text, tools=("set_todos",)):
    conn = SimpleNamespace(device_id=MAC, logger=logger, features={"mcp": True})
    conn.mcp_client = FakeMCPClient(tools)
    conn.websocket = FakeWS(conn, receipt_text)
    return conn


class TestMcpHandlerWiring:
    async def test_set_todos_call_reports_receipt_full_list(self, monkeypatch):
        reported = []

        async def fake_report(mac, todos):
            reported.append((mac, todos))

        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_report)
        todos = [{"text": "读绘本", "done": False}, {"text": "刷牙", "done": True}]
        receipt = json.dumps({"ok": True, "todos": todos}, ensure_ascii=False)
        conn = wire_conn(receipt)
        raw = await call_mcp_tool(conn, conn.mcp_client, "set_todos",
                                  json.dumps({"action": "add", "text": "读绘本"}))
        assert raw == receipt  # 原返回值不受挂钩影响
        await drain()
        assert reported == [(MAC, todos)]

    async def test_other_tool_and_failed_receipt_do_not_report(self, monkeypatch):
        reported = []

        async def fake_report(mac, todos):
            reported.append(mac)

        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_report)
        conn = wire_conn("ok", tools=("update_progress",))  # 非 set_todos 工具
        await call_mcp_tool(conn, conn.mcp_client, "update_progress", {})
        conn2 = wire_conn(json.dumps({"ok": False, "todos": []}))  # set_todos 但失败 receipt
        await call_mcp_tool(conn2, conn2.mcp_client, "set_todos", json.dumps({"action": "list"}))
        await drain()
        assert reported == []
