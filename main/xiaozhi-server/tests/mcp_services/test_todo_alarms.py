"""设备 Todo 截止提醒测试（spec #30 T4 / #34）：闹钟翻译 + 簿记联动 + 上线对账 + 下发剥离 due。

mock 边界收在 manage_api_client 与连接对象处（FakeMCPClient/FakeWS/wire_conn 收敛在 conftest），
走真实 call_mcp_tool 路径验证 self.clock.* 出参与簿记状态。
"""
import asyncio
import json

import pytest

from mcp_services import todo_sync
from tests.mcp_services.conftest import wire_conn

MAC = "AA:BB:CC:DD:EE:FF"

# 提醒播报文本（message 同时是簿记/对账恢复的匹配键）
MSG_1H = "还有1小时到截止:写作业"
MSG_30M = "还有半小时到截止:写作业"


class TestTranslateDue:
    """due → due−1h / due−30m 两个提醒点；静默时段内不设；deadline<=now 的过期点过滤。"""

    def test_due_yields_two_points_in_time_order(self):
        specs = todo_sync.translate_due("20:30", "写作业", now_hm="10:00")
        assert specs == [
            {"kind": "1h", "time": "19:30", "message": "还有1小时到截止:写作业"},
            {"kind": "30m", "time": "20:00", "message": "还有半小时到截止:写作业"},
        ]

    def test_points_inside_quiet_window_are_dropped(self):
        # due 21:30（默认静默 21:00–07:00）：1h 点 20:30 可设，30m 点 21:00 落静默 → 不设
        specs = todo_sync.translate_due("21:30", "写作业", now_hm="10:00")
        assert specs == [{"kind": "1h", "time": "20:30", "message": "还有1小时到截止:写作业"}]

    def test_all_points_in_quiet_window_yields_none(self):
        # due 22:00：21:00 / 21:30 均在静默内 → 无提醒点
        assert todo_sync.translate_due("22:00", "写作业", now_hm="10:00") == []

    def test_quiet_boundary_start_inclusive_end_exclusive(self):
        # 点 21:00 恰在静默起始 → 不设；点 07:00 恰在结束 → 可设（due 08:00 两点 07:00/07:30 均在静默外）
        assert todo_sync.translate_due("21:30", "x", now_hm="10:00") == [
            {"kind": "1h", "time": "20:30", "message": "还有1小时到截止:x"}]
        specs = todo_sync.translate_due("08:00", "x", now_hm="06:00")
        assert [s["time"] for s in specs] == ["07:00", "07:30"]

    def test_custom_quiet_window(self):
        # 设备级配置 22:00–08:00：due 21:30 的两个点 20:30/21:00 均可设
        specs = todo_sync.translate_due("21:30", "写作业", now_hm="10:00",
                                        quiet_start="22:00", quiet_end="08:00")
        assert [s["time"] for s in specs] == ["20:30", "21:00"]

    def test_past_points_are_dropped_to_prevent_tomorrow_ghost_alarm(self):
        # now 20:10、due 20:30：19:30 与 20:00 均已过 → 过滤后才可能调 set_alarm
        assert todo_sync.translate_due("20:30", "写作业", now_hm="20:10") == []
        # due 21:00：19:30/20:00 过期丢弃，20:30 保留
        specs = todo_sync.translate_due("21:00", "写作业", now_hm="20:10")
        assert [s["time"] for s in specs] == ["20:30"]

    def test_point_equal_to_now_is_dropped(self):
        # deadline<=now：等于现在的点同样丢弃（设备会顺延明天）——due 20:30、now 20:00 → 30m 点恰为 20:00
        assert todo_sync.translate_due("20:30", "x", now_hm="20:00") == []

    def test_midnight_wrap_negative_point_dropped(self):
        # due 01:00：1h 点 00:00（now 00:05 已过）丢弃、30m 点 00:30 保留（静默窗避开凌晨）；
        # due 00:30 的 1h 点为负（昨日）→ 丢弃、30m 点 00:00 已过 → 丢弃
        specs = todo_sync.translate_due("01:00", "x", now_hm="00:05",
                                        quiet_start="21:00", quiet_end="21:30")
        assert [s["time"] for s in specs] == ["00:30"]
        assert todo_sync.translate_due("00:30", "x", now_hm="00:05",
                                        quiet_start="21:00", quiet_end="21:30") == []

    def test_invalid_due_yields_no_points(self):
        assert todo_sync.translate_due("25:00", "x") == []
        assert todo_sync.translate_due("", "x") == []
        assert todo_sync.translate_due(None, "x") == []

    def test_late_night_due_next_morning_crosses_midnight(self):
        # H5：23:50 设次日 01:00 截止（65 分钟后）——due 当日读数已过 → 视为次日，
        # 00:00 / 00:30 两个提醒点是未来，不得当过期点过滤掉
        specs = todo_sync.translate_due("01:00", "写作业", now_hm="23:50",
                                        quiet_start="21:00", quiet_end="21:30")
        assert [s["time"] for s in specs] == ["00:00", "00:30"]
        assert [s["kind"] for s in specs] == ["1h", "30m"]

    def test_due_equal_to_now_is_not_treated_as_next_day(self):
        # H5 边界：due 恰为 now 不 +1440（两个提醒点均已过 → 空）
        assert todo_sync.translate_due("10:00", "x", now_hm="10:00",
                                       quiet_start="21:00", quiet_end="21:30") == []


# ───────────────────────── MCP 闹钟链路（真实 call_mcp_tool 路径） ─────────────────────────

CLOCK_TOOLS = ("set_todos", "self_clock_set_alarm", "self_clock_cancel", "self_clock_list")


class Toolbox:
    """设备端回环：按工具名预设 receipt；记录全部 tools/call 出参。
    set_alarm 自动发号并登记在册（self.clock.list 如实反映，含预置闹钟）。
    set_alarm_receipt 非 None → set_alarm 回执原样返回（仍登记在册），模拟不带 id 键的固件回执。"""

    def __init__(self, todos_receipt='{"ok": true, "todos": []}', listed=None):
        self.calls = []  # (tool_name, arguments)
        self.next_alarm_id = 10
        self.todos_receipt = todos_receipt
        self.device_alarms = list(listed.get("alarms", [])) if listed else []  # 设备闹钟在册表
        self.set_alarm_reply = None  # Exception → future 结算为异常
        self.set_alarm_receipt = None  # 非 None → set_alarm 回执原样用（如 '{"ok": true}' 无 id）
        self.cancel_reply = '{"id": 0, "cancelled": true}'

    def responder(self, name, args):
        """conftest.FakeWS 的 responder：先记录出参再按工具名结算回执。"""
        self.calls.append((name, args))
        return self.receipt_for(name, args)

    def receipt_for(self, name, args):
        if name == "set_todos":
            return self.todos_receipt
        if name == "self_clock_set_alarm":
            if isinstance(self.set_alarm_reply, Exception):
                return self.set_alarm_reply
            alarm_id = self.next_alarm_id
            self.next_alarm_id += 1
            self.device_alarms.append({"id": alarm_id, "type": "alarm",
                                       "ring_at": f"10-27 {args.get('time', '00:00')}",
                                       "message": args.get("message", "")})
            if self.set_alarm_receipt is not None:
                return self.set_alarm_receipt
            return json.dumps({"id": alarm_id, "type": "alarm",
                               "ring_at": f"10-27 {args.get('time', '00:00')}",
                               "in_minutes": 1, "message": args.get("message", "")})
        if name == "self_clock_cancel":
            self.device_alarms = [a for a in self.device_alarms if a.get("id") != args.get("id")]
            return self.cancel_reply
        if name == "self_clock_list":
            return json.dumps({"count": len(self.device_alarms), "alarms": self.device_alarms},
                              ensure_ascii=False)
        return "ok"


def wire_toolbox(toolbox, mac=MAC, tools=CLOCK_TOOLS, ready=True):
    return wire_conn(mac, toolbox.responder, tools=tools, ready=ready)


def clock_calls(toolbox, name):
    return [args for tool, args in toolbox.calls if tool == name]


@pytest.fixture(autouse=True)
def _clean_bookkeeping():
    yield
    for task in list(todo_sync._bg_tasks):
        task.cancel()
    todo_sync._bg_tasks.clear()
    todo_sync._alarms.clear()
    todo_sync._quiet_cfg.clear()
    todo_sync._ensured_conns.clear()
    todo_sync._connections.clear()


@pytest.fixture
def fixed_now(monkeypatch):
    """冻结「现在」为 10:00：提醒点 19:30/20:00 恒为未来，过滤行为可断言。"""
    monkeypatch.setattr(todo_sync, "_now_min", lambda: 10 * 60)
    return 10 * 60


def seed_record(text="写作业", kind="30m", time="20:00", message=MSG_30M, alarm_id=5):
    return {"text": text, "kind": kind, "time": time, "message": message, "id": alarm_id}


def pending_row(items, quiet=("21:00", "07:00")):
    row = {"mac": MAC, "items": items}
    if quiet:
        row["quietStart"], row["quietEnd"] = quiet
    return row


def stub_manage_api(monkeypatch, pending_rows=None):
    async def fake_pending():
        return pending_rows
    async def fake_delivered(mac, items):
        return None
    async def fake_online(macs):
        return None
    monkeypatch.setattr("config.manage_api_client.get_todo_pending", fake_pending)
    monkeypatch.setattr("config.manage_api_client.report_todo_delivered", fake_delivered)
    monkeypatch.setattr("config.manage_api_client.report_online_macs", fake_online)


class TestDownlinkStripAndReset:
    """下发链路：设备契约剥离 due；送达成功按最新 items 设当日闹钟（先 cancel 旧映射）。"""

    async def test_device_payload_strips_due(self, monkeypatch, fixed_now):
        echo = json.dumps({"ok": True, "todos": [{"text": "写作业", "done": False}]}, ensure_ascii=False)
        toolbox = Toolbox(todos_receipt=echo)
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        stub_manage_api(monkeypatch, [pending_row([{"text": "写作业", "done": False, "due": "20:30"}])])

        await todo_sync.run_sync_cycle()

        (args,) = clock_calls(toolbox, "set_todos")
        assert args["text"] == json.dumps([{"text": "写作业", "done": False}], ensure_ascii=False)

    async def test_push_success_sets_translated_alarm_pair(self, monkeypatch, fixed_now):
        echo = json.dumps({"ok": True, "todos": [{"text": "写作业", "done": False}]}, ensure_ascii=False)
        toolbox = Toolbox(todos_receipt=echo)
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        stub_manage_api(monkeypatch, [pending_row([{"text": "写作业", "done": False, "due": "20:30"}])])

        await todo_sync.run_sync_cycle()

        set_calls = clock_calls(toolbox, "self_clock_set_alarm")
        assert [(a["time"], a["message"]) for a in set_calls] == [("19:30", MSG_1H), ("20:00", MSG_30M)]
        assert all(r["id"] is not None for r in todo_sync._alarms[MAC])  # 簿记已确认

    async def test_push_cancels_old_booked_alarms_before_resetting(self, monkeypatch, fixed_now):
        echo = json.dumps({"ok": True, "todos": [{"text": "新任务", "done": False}]}, ensure_ascii=False)
        toolbox = Toolbox(todos_receipt=echo)
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        todo_sync._alarms[MAC] = [seed_record(text="旧任务", message="还有半小时到截止:旧任务", alarm_id=77)]
        stub_manage_api(monkeypatch, [pending_row([{"text": "新任务", "done": False}])])

        await todo_sync.run_sync_cycle()

        assert {"id": 77} in clock_calls(toolbox, "self_clock_cancel")
        assert todo_sync._alarms[MAC] == []  # 新清单无截止：旧映射清空、无新闹钟

    async def test_done_or_rewritten_items_get_no_alarm(self, monkeypatch, fixed_now):
        # 送达期间孩子勾掉一项、另一项文本被改写（不在回执）：均不设闹钟
        echo = json.dumps({"ok": True, "todos": [{"text": "读绘本", "done": False}]}, ensure_ascii=False)
        toolbox = Toolbox(todos_receipt=echo)
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        stub_manage_api(monkeypatch, [pending_row([
            {"text": "写作业", "done": False, "due": "20:30"},   # 回执里已完成 → 不设
            {"text": "改写后的任务", "done": False, "due": "20:30"},  # 不在回执 → 不设
        ])])
        # 回执只有 读绘本 未完成 → 上面两项都不设
        echo2 = json.dumps({"ok": True, "todos": [
            {"text": "写作业", "done": True}, {"text": "读绘本", "done": False}]}, ensure_ascii=False)
        toolbox.todos_receipt = echo2

        await todo_sync.run_sync_cycle()

        assert clock_calls(toolbox, "self_clock_set_alarm") == []
        assert todo_sync._alarms[MAC] == []

    async def test_quiet_from_pending_row_applies_to_translation(self, monkeypatch, fixed_now):
        # 设备级静默 20:30–07:00（随 pending 行下发）：due 21:00 的 30m 点 20:30 落静默 → 只设 1h 点 20:00
        echo = json.dumps({"ok": True, "todos": [{"text": "写作业", "done": False}]}, ensure_ascii=False)
        toolbox = Toolbox(todos_receipt=echo)
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        stub_manage_api(monkeypatch, [pending_row(
            [{"text": "写作业", "done": False, "due": "21:00"}], quiet=("20:30", "07:00"))])

        await todo_sync.run_sync_cycle()

        assert [a["time"] for a in clock_calls(toolbox, "self_clock_set_alarm")] == ["20:00"]

    async def test_old_firmware_without_clock_tools_skips_alarms(self, monkeypatch, fixed_now):
        echo = json.dumps({"ok": True, "todos": [{"text": "写作业", "done": False}]}, ensure_ascii=False)
        toolbox = Toolbox(todos_receipt=echo)
        conn = wire_toolbox(toolbox, tools=("set_todos",))  # 旧固件：无 self.clock.*
        todo_sync.register_connection(MAC, conn)
        stub_manage_api(monkeypatch, [pending_row([{"text": "写作业", "done": False, "due": "20:30"}])])

        await todo_sync.run_sync_cycle()  # 下发照常、提醒静默跳过

        assert clock_calls(toolbox, "set_todos")
        assert todo_sync._alarms[MAC] == []


class TestVoiceCancel:
    """语音 receipt 联动：任务完成 / 文本消失（删除、改写）→ 按簿记 cancel。"""

    async def test_completed_task_alarms_cancelled(self, monkeypatch):
        toolbox = Toolbox()
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        todo_sync._alarms[MAC] = [
            seed_record(kind="1h", time="19:30", message=MSG_1H, alarm_id=11),
            seed_record(alarm_id=12),
            seed_record(text="刷牙", message="还有半小时到截止:刷牙", alarm_id=13),
        ]
        async def fake_report(mac, items):
            return None
        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_report)

        # 语音：写作业做完勾选、刷牙未动
        todo_sync.on_set_todos_receipt(conn, json.dumps({"ok": True, "todos": [
            {"text": "写作业", "done": True}, {"text": "刷牙", "done": False}]}, ensure_ascii=False))
        await asyncio.wait_for(asyncio.gather(*list(todo_sync._bg_tasks)), timeout=2)

        assert sorted(a["id"] for a in clock_calls(toolbox, "self_clock_cancel")) == [11, 12]
        assert [r["text"] for r in todo_sync._alarms[MAC]] == ["刷牙"]  # 未完成任务的提醒保留

    async def test_deleted_or_rewritten_text_cancels_alarms(self, monkeypatch):
        toolbox = Toolbox()
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        todo_sync._alarms[MAC] = [seed_record(alarm_id=21)]
        async def fake_report(mac, items):
            return None
        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_report)

        # 语音改写 = remove+add：旧文本「写作业」从清单消失
        todo_sync.on_set_todos_receipt(conn, json.dumps({"ok": True, "todos": [
            {"text": "写作业（数学）", "done": False}]}, ensure_ascii=False))
        await asyncio.wait_for(asyncio.gather(*list(todo_sync._bg_tasks)), timeout=2)

        assert clock_calls(toolbox, "self_clock_cancel") == [{"id": 21}]
        assert todo_sync._alarms[MAC] == []

    async def test_no_bookkeeping_means_no_clock_calls(self, monkeypatch):
        toolbox = Toolbox()
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        async def fake_report(mac, items):
            return None
        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_report)

        todo_sync.on_set_todos_receipt(conn, json.dumps({"ok": True, "todos": [
            {"text": "写作业", "done": True}]}, ensure_ascii=False))
        await asyncio.sleep(0)

        assert toolbox.calls == []


class TestReconcile:
    """上线对账：self.clock.list 以 message 为匹配键——设备丢闹钟重设（过期不设）、server 重启收养。"""

    async def test_device_reboot_resets_missing_booked_alarms(self, monkeypatch, fixed_now):
        toolbox = Toolbox()  # 设备重启后闹钟在册表为空（重启丢闹钟）
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        todo_sync._alarms[MAC] = [seed_record(alarm_id=5), seed_record(kind="1h", time="19:30", message=MSG_1H, alarm_id=6)]
        stub_manage_api(monkeypatch, [])

        await todo_sync.run_sync_cycle()

        resets = clock_calls(toolbox, "self_clock_set_alarm")
        # 重设顺序即簿记顺序；id 按新回执更新
        assert [(a["time"], a["message"]) for a in resets] == [("20:00", MSG_30M), ("19:30", MSG_1H)]
        assert all(r["id"] not in (None, 5, 6) for r in todo_sync._alarms[MAC])

    async def test_expired_missing_alarm_is_dropped_not_reset(self, monkeypatch):
        monkeypatch.setattr(todo_sync, "_now_min", lambda: 10 * 60 + 30)  # 10:30
        toolbox = Toolbox(listed={"count": 0, "alarms": []})
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        todo_sync._alarms[MAC] = [seed_record(time="10:00", alarm_id=5)]  # 提醒点已过
        stub_manage_api(monkeypatch, [])

        await todo_sync.run_sync_cycle()

        assert clock_calls(toolbox, "self_clock_set_alarm") == []  # 不重设：防顺延成次日幽灵闹钟
        assert todo_sync._alarms[MAC] == []

    async def test_server_restart_adopts_device_alarms_by_message(self, monkeypatch, fixed_now):
        toolbox = Toolbox(listed={"count": 1, "alarms": [
            {"id": 99, "type": "alarm", "ring_at": "10-27 20:00", "in_minutes": 600, "message": MSG_30M},
        ]})
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        stub_manage_api(monkeypatch, [])

        await todo_sync.run_sync_cycle()

        adopted = todo_sync._alarms[MAC]
        assert [(r["text"], r["kind"], r["time"], r["id"]) for r in adopted] == [("写作业", "30m", "20:00", 99)]

        # 收养后的簿记可联动：语音完成写作业 → cancel 设备上的 99
        async def fake_report(mac, items):
            return None
        monkeypatch.setattr("config.manage_api_client.report_todo_list", fake_report)
        todo_sync.on_set_todos_receipt(conn, json.dumps({"ok": True, "todos": [
            {"text": "写作业", "done": True}]}, ensure_ascii=False))
        await asyncio.wait_for(asyncio.gather(*list(todo_sync._bg_tasks)), timeout=2)
        assert clock_calls(toolbox, "self_clock_cancel") == [{"id": 99}]

    async def test_stable_connection_not_relisted_every_cycle(self, monkeypatch, fixed_now):
        toolbox = Toolbox()
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        stub_manage_api(monkeypatch, [])

        await todo_sync.run_sync_cycle()
        await todo_sync.run_sync_cycle()

        assert len(clock_calls(toolbox, "self_clock_list")) == 1  # 连接未变且无未确认 → 不重复对账


class TestRetrySemantics:
    """set_alarm「时间未同步」error 可重试：簿记不确认，下轮循环自然重试到成功。"""

    async def test_time_not_synced_keeps_unconfirmed_then_retries(self, monkeypatch, fixed_now):
        echo = json.dumps({"ok": True, "todos": [{"text": "写作业", "done": False}]}, ensure_ascii=False)
        toolbox = Toolbox(todos_receipt=echo)
        toolbox.set_alarm_reply = RuntimeError("MCP错误: Device time is not synced yet, cannot set an alarm")
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        stub_manage_api(monkeypatch, [pending_row([{"text": "写作业", "done": False, "due": "20:30"}])])

        await todo_sync.run_sync_cycle()

        # 下发与回执照常（清单不受闹钟影响）；簿记留未确认记录
        assert clock_calls(toolbox, "set_todos")
        assert len(todo_sync._alarms[MAC]) == 2
        assert all(r["id"] is None for r in todo_sync._alarms[MAC])

        toolbox.set_alarm_reply = None  # 设备校时完成
        async def pending_empty():
            return []
        monkeypatch.setattr("config.manage_api_client.get_todo_pending", pending_empty)
        await todo_sync.run_sync_cycle()

        assert all(r["id"] is not None for r in todo_sync._alarms[MAC])  # 重试到成功并确认

    async def test_permanent_set_alarm_error_drops_records(self, monkeypatch, fixed_now):
        echo = json.dumps({"ok": True, "todos": [{"text": "写作业", "done": False}]}, ensure_ascii=False)
        toolbox = Toolbox(todos_receipt=echo)
        toolbox.set_alarm_reply = ValueError("boom")
        conn = wire_toolbox(toolbox)
        todo_sync.register_connection(MAC, conn)
        stub_manage_api(monkeypatch, [pending_row([{"text": "写作业", "done": False, "due": "20:30"}])])

        await todo_sync.run_sync_cycle()

        assert todo_sync._alarms[MAC] == []  # 非时间未同步错误：放弃，不无限重试
