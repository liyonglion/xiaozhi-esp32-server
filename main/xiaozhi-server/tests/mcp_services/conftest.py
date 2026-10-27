"""math_practice 测试的显示消息采集 + todo 测试共用的设备端 MCP 回环桩。

显示消息：优先用真实 core.handle.sendAudioHandle（写入 conn.websocket.send，FakeWS 采集）；
仅当本地依赖缺失导入失败时才装 stub（直接写入 conn.sent），避免顶替真模块
导致其他测试（如 test_tts 经 reportHandle 导入 sendAudioMessage）失败。

MCP 回环（FakeMCPClient/FakeWS/wire_conn）：test_todo_sync/downlink/alarms 三份复制的
设备端桩收敛于此——call_mcp_tool 走真实出参/回执路径，回执由 responder(tool, args) 预设。
"""
import asyncio
import json
import sys
import types
from types import SimpleNamespace

from loguru import logger

try:
    import core.handle.sendAudioHandle  # noqa: F401
except Exception:
    _stub = types.ModuleType("core.handle.sendAudioHandle")
    _stub.__file__ = __file__

    async def send_display_message(conn, text):
        conn.sent.append({"type": "stt", "text": text})

    async def send_tts_message(conn, state, text=None):
        if text is not None:
            conn.sent.append({"type": "tts", "state": state, "text": text})

    _stub.send_display_message = send_display_message
    _stub.send_tts_message = send_tts_message
    sys.modules.setdefault("core.handle.sendAudioHandle", _stub)


# ───────────────────────── todo 测试共用：设备端 MCP 回环桩 ─────────────────────────

class FakeMCPClient:
    """设备 MCP 客户端桩：tools 注册表 + per-call future（call_mcp_tool 走真实路径）。"""

    def __init__(self, tools=("set_todos",), ready=True):
        self.tools = {name: {"description": name, "inputSchema": {}} for name in tools}
        self.name_mapping = {}
        self.ready = ready
        self.futures = {}

    def has_tool(self, name):
        return name in self.tools

    async def is_ready(self):
        return self.ready

    async def get_next_id(self):
        return len(self.futures) + 1

    async def register_call_result_future(self, tid, future):
        self.futures[tid] = future

    async def cleanup_call_result_future(self, tid):
        self.futures.pop(tid, None)

    async def cleanup_call_result(self, tid):
        self.futures.pop(tid, None)


class FakeWS:
    """设备端回环：记录全部出参，按 responder(tool, args) 预设回执结算 future。

    responder 返回 str=成功回执、Exception=失败回执、None=不结算（调用挂起，模拟在途窗口）。
    """

    def __init__(self, conn, responder):
        self._conn = conn
        self._responder = responder
        self.sent = []

    async def send(self, message):
        m = json.loads(message)
        self.sent.append(m)
        mc = self._conn.mcp_client
        if m.get("type") == "mcp" and m["payload"].get("method") == "tools/call":
            fut = mc.futures.get(m["payload"]["id"])
            if fut and not fut.done():
                reply = self._responder(m["payload"]["params"]["name"],
                                        m["payload"]["params"].get("arguments"))
                if isinstance(reply, Exception):
                    fut.set_exception(reply)
                elif reply is not None:
                    fut.set_result({"content": [{"text": reply}]})


def static_receipt(text):
    """最简 responder：任何工具都回固定文本。"""
    return lambda tool, args: text


def wire_conn(mac, responder, tools=("set_todos",), ready=True):
    conn = SimpleNamespace(device_id=mac, logger=logger, features={"mcp": True})
    conn.mcp_client = FakeMCPClient(tools, ready=ready)
    conn.websocket = FakeWS(conn, responder)
    return conn


async def tick(seconds=0.02):
    """真实让出事件循环若干秒（顶层 conftest 把 asyncio.sleep 换成了不 yield 的空操作）。"""
    try:
        await asyncio.wait_for(asyncio.Event().wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
