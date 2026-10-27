"""设备 Todo 下发闭环测试（spec #30 T2 / #32）：连接注册表 + 60s 循环扫 pending → set_todos(replace) → 清 pending。

mock 边界收在 manage_api_client 与连接对象处（FakeMCPClient/FakeWS/wire_conn 收敛在 conftest），
走真实 call_mcp_tool 路径验证 MCP 出参与 receipt 挂钩抑制。
"""
import asyncio
import contextlib
import json

import pytest

from mcp_services import todo_sync
from tests.mcp_services.conftest import static_receipt, tick, wire_conn

MAC_A = "AA:AA:AA:AA:AA:01"
MAC_B = "AA:AA:AA:AA:AA:02"


def wire_static(mac, receipt_text='{"ok": true, "todos": []}', tools=("set_todos",), ready=True):
    return wire_conn(mac, static_receipt(receipt_text), tools=tools, ready=ready)


def pending_entry(mac, items):
    return {"mac": mac, "items": [{"text": t, "done": d} for t, d in items]}


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    todo_sync._connections.clear()
    todo_sync._alarms.clear()
    todo_sync._quiet_cfg.clear()
    todo_sync._ensured_conns.clear()
    todo_sync._pushing_tasks.clear()


class TestConnectionRegistry:
    """模块级 mac→conn 注册表（照 math _timers dict 先例）：重连顶替与注销身份守卫。"""

    def test_register_and_lookup(self):
        conn = wire_static(MAC_A)
        todo_sync.register_connection(MAC_A, conn)
        assert todo_sync.connection_for(MAC_A) is conn
        assert todo_sync.connection_for(MAC_B) is None

    def test_reconnect_replaces_and_old_close_does_not_evict_new(self):
        old, new = wire_static(MAC_A), wire_static(MAC_A)
        todo_sync.register_connection(MAC_A, old)
        todo_sync.register_connection(MAC_A, new)  # 重连：新句柄顶替
        todo_sync.unregister_connection(MAC_A, old)  # 旧连接随后关闭
        assert todo_sync.connection_for(MAC_A) is new

    def test_unregister_unknown_mac_is_noop(self):
        todo_sync.unregister_connection(MAC_B, wire_static(MAC_B))  # 不抛错即通过

    def test_unregister_clears_per_mac_bookkeeping(self):
        """H7：注销联动清理簿记/对账标记/静默配置——设备更替下 ConnectionHandler
        （websocket/缓冲）等死引用不无界累积。"""
        conn = wire_static(MAC_A)
        todo_sync.register_connection(MAC_A, conn)
        todo_sync._alarms[MAC_A] = [{"text": "x", "kind": "30m", "time": "20:00",
                                     "message": "m", "id": 1, "confirmed": True}]
        todo_sync._ensured_conns[MAC_A] = conn  # 持连接引用的正是这里
        todo_sync._quiet_cfg[MAC_A] = ("21:00", "07:00")

        todo_sync.unregister_connection(MAC_A, conn)

        assert todo_sync.connection_for(MAC_A) is None
        assert MAC_A not in todo_sync._alarms
        assert MAC_A not in todo_sync._ensured_conns
        assert MAC_A not in todo_sync._quiet_cfg


class TestSyncCycle:
    """60s 循环的单轮：上报在线集合 → 拉 pending → 在线且有工具的设备 replace 下发 → 回执 ok 清 pending。"""

    async def test_pushes_pending_to_online_device_and_clears(self, monkeypatch):
        todos = [{"text": "读绘本", "done": False}]
        receipt = json.dumps({"ok": True, "todos": todos}, ensure_ascii=False)
        conn = wire_static(MAC_A, receipt)
        todo_sync.register_connection(MAC_A, conn)
        online_reports, delivered, pending_pulls = [], [], []

        async def fake_pending():
            pending_pulls.append(True)
            return [pending_entry(MAC_A, [("读绘本", False)])]

        async def fake_delivered(mac, items):
            delivered.append((mac, items))

        async def fake_online(macs):
            online_reports.append(list(macs))

        monkeypatch.setattr("config.manage_api_client.get_todo_pending", fake_pending)
        monkeypatch.setattr("config.manage_api_client.report_todo_delivered", fake_delivered)
        monkeypatch.setattr("config.manage_api_client.report_online_macs", fake_online)

        await todo_sync.run_sync_cycle()

        assert online_reports == [[MAC_A]]  # 注册表即在线集合
        assert delivered == [(MAC_A, todos)]  # 回执内容回传清 pending
        call = conn.websocket.sent[0]["payload"]
        assert call["method"] == "tools/call"
        assert call["params"]["name"] == "set_todos"
        assert call["params"]["arguments"] == {
            "action": "replace",
            "text": json.dumps(todos, ensure_ascii=False),  # 设备契约：全量 JSON 数组字符串
        }

    async def test_offline_device_keeps_pending(self, monkeypatch):
        delivered = []

        async def fake_pending():
            return [pending_entry(MAC_A, [("读绘本", False)])]  # pending 但注册表无连接

        async def fake_delivered(mac, items):
            delivered.append(mac)

        async def fake_online(macs):
            return None

        monkeypatch.setattr("config.manage_api_client.get_todo_pending", fake_pending)
        monkeypatch.setattr("config.manage_api_client.report_todo_delivered", fake_delivered)
        monkeypatch.setattr("config.manage_api_client.report_online_macs", fake_online)

        await todo_sync.run_sync_cycle()  # 不抛错即通过（离线静默保留 pending）

        assert delivered == []

    async def test_old_firmware_without_tool_is_skipped(self, monkeypatch):
        conn = wire_static(MAC_A, tools=("get_time",))  # 未注册 set_todos 的旧固件
        todo_sync.register_connection(MAC_A, conn)
        delivered = []

        async def fake_pending():
            return [pending_entry(MAC_A, [("读绘本", False)])]

        async def fake_delivered(mac, items):
            delivered.append(mac)

        async def fake_online(macs):
            return None

        monkeypatch.setattr("config.manage_api_client.get_todo_pending", fake_pending)
        monkeypatch.setattr("config.manage_api_client.report_todo_delivered", fake_delivered)
        monkeypatch.setattr("config.manage_api_client.report_online_macs", fake_online)

        await todo_sync.run_sync_cycle()

        assert delivered == []
        assert conn.websocket.sent == []  # 未发起任何 MCP 调用

    async def test_failed_receipt_keeps_pending_for_retry(self, monkeypatch):
        conn = wire_static(MAC_A, '{"ok": false, "todos": []}')  # 设备拒绝（如 NVS 写满）
        todo_sync.register_connection(MAC_A, conn)
        delivered = []

        async def fake_pending():
            return [pending_entry(MAC_A, [("读绘本", False)])]

        async def fake_delivered(mac, items):
            delivered.append(mac)

        async def fake_online(macs):
            return None

        monkeypatch.setattr("config.manage_api_client.get_todo_pending", fake_pending)
        monkeypatch.setattr("config.manage_api_client.report_todo_delivered", fake_delivered)
        monkeypatch.setattr("config.manage_api_client.report_online_macs", fake_online)

        await todo_sync.run_sync_cycle()

        assert delivered == []  # 不清 pending，下一轮重试

    async def test_devices_pushed_in_pending_order(self, monkeypatch):
        """FIFO 保序：pending 顺序即下发顺序（单循环内逐台 await，天然保序）。"""
        conns = {}
        receipts = {}
        for mac in (MAC_A, MAC_B):
            todos = [{"text": mac, "done": False}]
            receipts[mac] = json.dumps({"ok": True, "todos": todos}, ensure_ascii=False)
            conns[mac] = wire_static(mac, receipts[mac])
            todo_sync.register_connection(mac, conns[mac])
        delivered = []

        async def fake_pending():
            return [pending_entry(MAC_A, [(MAC_A, False)]), pending_entry(MAC_B, [(MAC_B, False)])]

        async def fake_delivered(mac, items):
            delivered.append(mac)

        async def fake_online(macs):
            return None

        monkeypatch.setattr("config.manage_api_client.get_todo_pending", fake_pending)
        monkeypatch.setattr("config.manage_api_client.report_todo_delivered", fake_delivered)
        monkeypatch.setattr("config.manage_api_client.report_online_macs", fake_online)

        await todo_sync.run_sync_cycle()

        assert delivered == [MAC_A, MAC_B]

    async def test_downlink_push_does_not_fire_voice_report_hook(self, monkeypatch):
        """下发 replace 的 receipt 不走 T1 语音上报（否则旧内容回写镜像、来源错记 voice）。"""
        todos = [{"text": "读绘本", "done": False}]
        conn = wire_static(MAC_A, json.dumps({"ok": True, "todos": todos}, ensure_ascii=False))
        todo_sync.register_connection(MAC_A, conn)
        voice_reports = []

        async def fake_voice_report(mac, items):
            voice_reports.append(mac)

        async def fake_pending():
            return [pending_entry(MAC_A, [("读绘本", False)])]

        async def fake_delivered(mac, items):
            return None

        async def fake_online(macs):
            return None

        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_voice_report)
        monkeypatch.setattr("config.manage_api_client.get_todo_pending", fake_pending)
        monkeypatch.setattr("config.manage_api_client.report_todo_delivered", fake_delivered)
        monkeypatch.setattr("config.manage_api_client.report_online_macs", fake_online)

        await todo_sync.run_sync_cycle()
        await asyncio.wait_for(asyncio.gather(*list(todo_sync._report_tasks)), timeout=2) if todo_sync._report_tasks else None

        assert voice_reports == []

    async def test_cycle_survives_api_failure(self, monkeypatch):
        """拉取失败不炸循环（下一轮重试），上报在线失败同样吞掉。"""

        async def boom():
            raise RuntimeError("api down")

        async def fake_online(macs):
            raise RuntimeError("api down")

        monkeypatch.setattr("config.manage_api_client.get_todo_pending", boom)
        monkeypatch.setattr("config.manage_api_client.report_online_macs", fake_online)

        await todo_sync.run_sync_cycle()  # 不抛错即通过

    async def test_mcp_not_ready_is_skipped(self, monkeypatch):
        conn = wire_static(MAC_A, ready=False)
        todo_sync.register_connection(MAC_A, conn)
        delivered = []

        async def fake_pending():
            return [pending_entry(MAC_A, [("读绘本", False)])]

        async def fake_delivered(mac, items):
            delivered.append(mac)

        async def fake_online(macs):
            return None

        monkeypatch.setattr("config.manage_api_client.get_todo_pending", fake_pending)
        monkeypatch.setattr("config.manage_api_client.report_todo_delivered", fake_delivered)
        monkeypatch.setattr("config.manage_api_client.report_online_macs", fake_online)

        await todo_sync.run_sync_cycle()

        assert delivered == []
        assert conn.websocket.sent == []


class TestSyncManagerLoop:
    """TodoSyncManager._loop：单轮未预见异常不得落出 while（否则下发/对账停摆到进程重启）。"""

    async def test_loop_survives_unexpected_cycle_error(self, monkeypatch):
        cycles = []

        async def flaky_cycle():
            cycles.append(1)
            if len(cycles) == 1:
                raise RuntimeError("unexpected bug")

        monkeypatch.setattr(todo_sync, "run_sync_cycle", flaky_cycle)
        manager = todo_sync.TodoSyncManager(interval_seconds=0.02)
        await manager.start()
        await tick(0.15)
        await manager.stop()

        assert len(cycles) >= 2  # 首轮炸掉后循环继续跑（修复前 catch-all 落出 while 只跑一轮）


class TestPushSuppression:
    """H2：下发抑制只作用于下发自身那次 set_todos 调用——在途期间孩子的语音 receipt 照常上报。"""

    async def test_voice_receipt_during_inflight_push_is_not_suppressed(self, monkeypatch):
        def responder(tool, args):
            if tool == "set_todos":
                return None  # 设备不回：下发调用挂在等待回执上（在途窗口，最长 30s）
            return '{"ok": true, "todos": []}'

        conn = wire_conn(MAC_A, responder)
        todo_sync.register_connection(MAC_A, conn)
        voice_reports = []

        async def fake_voice_report(mac, items):
            voice_reports.append((mac, items))

        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_voice_report)

        push = asyncio.ensure_future(
            todo_sync._push_and_confirm(conn, [{"text": "读绘本", "done": False}]))
        await tick(0.05)  # 下发调用已发出、正挂在 await 回执
        # 孩子语音「做完了」：receipt 挂钩在语音调用的 task 里触发（非下发 task），不得被抑制
        todo_sync.on_set_todos_receipt(conn, json.dumps(
            {"ok": True, "todos": [{"text": "读绘本", "done": True}]}, ensure_ascii=False))
        if todo_sync._report_tasks:
            await asyncio.wait_for(asyncio.gather(*list(todo_sync._report_tasks)), timeout=2)

        assert voice_reports == [(MAC_A, [{"text": "读绘本", "done": True}])]  # 完成事件不被吞

        push.cancel()  # 挂起的下发不再需要
        with contextlib.suppress(asyncio.CancelledError):
            await push
