"""儿童长期记忆 HTTP 面（工单 #10，缝：core/api/kids_memory_handler.py）。

被测行为：家长页经 manager-api 代理到达 8003 的三个端点——
- Bearer 密钥 == server.auth_key 才放行（manager-api 侧下发 server.secret）
- GET  list   → {"success": true, "data": [条目]}
- POST delete → {"success": true, "data": 是否删到}
- POST clear  → {"success": true, "data": true}
- 坏请求/内部错误 → success=false 且不抛出

直接以假 request 对象调 handler 方法（vision_handler 无 HTTP 测试先例，
socket/路由胶水 4 行归人工冒烟，见 docs/kids-companion.md）。
"""
from __future__ import annotations

import json

import pytest
import yaml

from core.api.kids_memory_handler import KidsMemoryHandler


class FakeRequest:
    def __init__(self, headers=None, json_body=None):
        self.headers = headers or {}
        self._json_body = json_body

    async def json(self):
        if self._json_body is None:
            raise ValueError("no body")
        return self._json_body


def _make_handler(auth_key="secret-abc"):
    return KidsMemoryHandler({"server": {"auth_key": auth_key}})


def _body(response) -> dict:
    return json.loads(response.text)


def test_all_endpoints_reject_wrong_or_missing_bearer():
    handler = _make_handler()
    requests = (
        FakeRequest(),
        FakeRequest(headers={"Authorization": "Bearer wrong"}),
        FakeRequest(headers={"Authorization": "secret-abc"}),  # 缺 Bearer 前缀
    )
    for request in requests:
        assert _run(handler.handle_list(request)).status == 401
        assert _run(handler.handle_delete(request)).status == 401
        assert _run(handler.handle_clear(request)).status == 401


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_list_returns_entries(tmp_path, monkeypatch):
    import core.providers.memory.mem_kids.mem_kids as mem_kids

    monkeypatch.setattr(mem_kids, "_STORE_PATH", str(tmp_path / ".memory_kids.yaml"))
    monkeypatch.setattr(mem_kids, "_INSTANCES", {})  # 隔离其它测试残留的活跃实例
    (tmp_path / ".memory_kids.yaml").write_text(
        yaml.safe_dump(
            {"kid-1": {"entries": [{"id": 1, "ts": 100, "text": "喜欢恐龙"}],
                        "summary": ""}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    handler = _make_handler()
    resp = _run(
        handler.handle_list(FakeRequest(headers={"Authorization": "Bearer secret-abc"}))
    )
    assert resp.status == 200
    body = _body(resp)
    assert body["success"] is True
    assert body["data"] == [{"id": 1, "ts": 100, "text": "喜欢恐龙"}]


def test_delete_removes_entry_and_reports_miss(tmp_path, monkeypatch):
    import core.providers.memory.mem_kids.mem_kids as mem_kids

    monkeypatch.setattr(mem_kids, "_STORE_PATH", str(tmp_path / ".memory_kids.yaml"))
    monkeypatch.setattr(mem_kids, "_INSTANCES", {})  # 隔离其它测试残留的活跃实例
    (tmp_path / ".memory_kids.yaml").write_text(
        yaml.safe_dump(
            {"kid-1": {"entries": [{"id": 1, "ts": 100, "text": "喜欢恐龙"}],
                        "summary": ""}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    handler = _make_handler()
    headers = {"Authorization": "Bearer secret-abc"}

    resp = _run(handler.handle_delete(FakeRequest(headers=headers, json_body={"id": 1})))
    assert resp.status == 200
    assert _body(resp) == {"success": True, "data": True}

    resp = _run(handler.handle_delete(FakeRequest(headers=headers, json_body={"id": 1})))
    assert _body(resp) == {"success": True, "data": False}

    data = yaml.safe_load((tmp_path / ".memory_kids.yaml").read_text(encoding="utf-8"))
    assert data["kid-1"]["entries"] == []


def test_delete_rejects_malformed_body():
    handler = _make_handler()
    resp = _run(
        handler.handle_delete(
            FakeRequest(
                headers={"Authorization": "Bearer secret-abc"}, json_body={"id": "abc"}
            )
        )
    )
    assert resp.status == 200
    body = _body(resp)
    assert body["success"] is False
    assert "message" in body


def test_clear_empties_store(tmp_path, monkeypatch):
    import core.providers.memory.mem_kids.mem_kids as mem_kids

    monkeypatch.setattr(mem_kids, "_STORE_PATH", str(tmp_path / ".memory_kids.yaml"))
    monkeypatch.setattr(mem_kids, "_INSTANCES", {})  # 隔离其它测试残留的活跃实例
    (tmp_path / ".memory_kids.yaml").write_text(
        yaml.safe_dump(
            {"kid-1": {"entries": [{"id": 1, "ts": 100, "text": "喜欢恐龙"}],
                        "summary": "孩子喜欢恐龙。"}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    handler = _make_handler()
    resp = _run(
        handler.handle_clear(FakeRequest(headers={"Authorization": "Bearer secret-abc"}))
    )
    assert _body(resp) == {"success": True, "data": True}
    data = yaml.safe_load((tmp_path / ".memory_kids.yaml").read_text(encoding="utf-8"))
    assert data["kid-1"] == {"entries": [], "summary": ""}


def test_internal_error_returns_failure_json(monkeypatch):
    import core.providers.memory.mem_kids.mem_kids as mem_kids

    def _boom():
        raise RuntimeError("store broken")

    monkeypatch.setattr(mem_kids, "list_for_role", _boom)
    handler = _make_handler()
    resp = _run(
        handler.handle_list(FakeRequest(headers={"Authorization": "Bearer secret-abc"}))
    )
    body = _body(resp)
    assert body["success"] is False
    assert "message" in body
