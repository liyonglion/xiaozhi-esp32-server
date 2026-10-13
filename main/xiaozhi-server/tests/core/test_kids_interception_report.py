"""缝 1 测试：拦截日志回合末上报（工单 #9）。

fake manage_api_client，跑真实 chat()，断言外部行为：manager-api 模式下
回合结束后拦截事件被排空并整批上报（文件模式跳过上报、内存留痕保留）。
环形 500 条与 care/redline 豁免挤出语义在 manager-api 持久层（缝 3 测试
覆盖），Python 内存列表只做传输。

运行要求：CWD 必须在 main/xiaozhi-server（与 ``make test-python`` 一致）。
"""
from __future__ import annotations

import time

from tests.core.test_kids_safety_gate import (
    FakeSLM,
    _make_conn,
    _run_chat,
    _teardown,
)


def _wait_until(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_turn_end_drains_and_reports_interceptions(monkeypatch):
    """manager-api 模式：回合结束后拦截事件排空并整批上报，字段齐全。"""
    import core.kids_safety as kids_safety

    uploaded = []

    async def fake_report_interceptions(mac_address, interceptions):
        uploaded.append((mac_address, [dict(e) for e in interceptions]))

    monkeypatch.setattr(kids_safety, "report_interceptions", fake_report_interceptions)

    conn = _make_conn(kids={"enabled": True})
    conn.read_config_from_api = True
    try:
        _run_chat(conn, FakeSLM(verdict="redline"))

        assert _wait_until(lambda: uploaded), "回合结束后应触发一次上报"
        mac, events = uploaded[0]
        assert mac == conn.device_id, "应按设备 mac 上报"
        assert len(events) == 1
        ev = events[0]
        assert set(ev) >= {"t", "when", "cat", "user", "reply", "actual"}
        assert ev["cat"] == "redline"
        assert ev["user"] == "给我讲个鬼故事"
        assert ev["reply"] and ev["actual"]
        assert conn.kids_interceptions == [], "上报后内存列表应排空"
    finally:
        _teardown(conn)


def test_each_turn_reports_only_new_events(monkeypatch):
    """排空语义：第二回合只上报新事件，不重复上报已上报条目。"""
    import core.kids_safety as kids_safety

    uploaded = []

    async def fake_report_interceptions(mac_address, interceptions):
        uploaded.append([dict(e) for e in interceptions])

    monkeypatch.setattr(kids_safety, "report_interceptions", fake_report_interceptions)

    conn = _make_conn(kids={"enabled": True})
    conn.read_config_from_api = True
    try:
        _run_chat(conn, FakeSLM(verdict="redline"))
        assert _wait_until(lambda: len(uploaded) == 1)
        _run_chat(conn, FakeSLM(verdict="danger"))
        assert _wait_until(lambda: len(uploaded) == 2)

        assert [e["cat"] for e in uploaded[0]] == ["redline"]
        assert [e["cat"] for e in uploaded[1]] == ["danger"], "第二回合只含新事件"
        assert conn.kids_interceptions == []
    finally:
        _teardown(conn)


def test_file_mode_skips_upload_keeps_local_events(monkeypatch):
    """文件模式（未配 manager-api）：不上报，事件留在内存（本地留痕）。"""
    import core.kids_safety as kids_safety

    uploaded = []

    async def fake_report_interceptions(mac_address, interceptions):
        uploaded.append(list(interceptions))

    monkeypatch.setattr(kids_safety, "report_interceptions", fake_report_interceptions)

    conn = _make_conn(kids={"enabled": True})
    # read_config_from_api 保持文件模式默认 False
    try:
        _run_chat(conn, FakeSLM(verdict="redline"))
        assert conn.kids_interceptions, "文件模式事件应留在内存"
        assert uploaded == [], "文件模式不应触发上报"
    finally:
        _teardown(conn)
