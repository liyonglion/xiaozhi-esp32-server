"""孩子档案下发通道消费测试（工单 #6，缝 2/配置面）。

档案经现有 per-agent 下发通道到达服务端：
- API 模式：manager-api getAgentModels 返回体带 kids 块（开关+档案统一
  扩展），_initialize_private_config_async 消费进 self.config["kids"]
  （照 summaryMemory 先例）
- 文件模式：config.yaml 顶层 kids 同名块经 merge_configs 合并，同一
  读取代码生效（fallback）

先例：tests/core/test_connection_slm.py 的 private_config mock 模式。
"""
from __future__ import annotations

import asyncio
import copy

import core.connection as connection_module
from core.connection import ConnectionHandler
from tests.conftest import CONFIG

KIDS_FROM_SERVER = {
    "enabled": True,
    "nickname": "小豆",
    "birth_ym": "2019-05",
}


def _make_handler() -> ConnectionHandler:
    config = copy.deepcopy(CONFIG)
    config.pop("kids", None)
    config["read_config_from_api"] = True
    handler = ConnectionHandler(config, None, None, None, None, None)
    handler.headers = {"device-id": "kids-config-test"}
    return handler


class TestKidsPrivateConfigConsumption:
    def test_kids_block_lands_in_connection_config(self, monkeypatch):
        """API 模式：下发的 kids 块被消费进 self.config，供 L2 渲染读取。"""
        handler = _make_handler()

        async def _fake_get_private_config(_config, *_args, **_kwargs):
            return {"kids": copy.deepcopy(KIDS_FROM_SERVER)}

        monkeypatch.setattr(
            connection_module, "get_private_config_from_api", _fake_get_private_config
        )
        monkeypatch.setattr(
            connection_module, "initialize_modules", lambda *args, **kwargs: {}
        )

        async def _scenario():
            handler.loop = asyncio.get_running_loop()
            await handler._initialize_private_config_async()

        asyncio.run(_scenario())

        assert handler.config["kids"] == KIDS_FROM_SERVER

    def test_absent_kids_block_leaves_config_untouched(self, monkeypatch):
        """API 模式：智控台没配档案 → 不写 kids 键，不影响既有配置。"""
        handler = _make_handler()

        async def _fake_get_private_config(_config, *_args, **_kwargs):
            return {}

        monkeypatch.setattr(
            connection_module, "get_private_config_from_api", _fake_get_private_config
        )
        monkeypatch.setattr(
            connection_module, "initialize_modules", lambda *args, **kwargs: {}
        )

        async def _scenario():
            handler.loop = asyncio.get_running_loop()
            await handler._initialize_private_config_async()

        asyncio.run(_scenario())

        assert "kids" not in handler.config


class TestFileModeFallback:
    def test_config_yaml_kids_block_reaches_merged_config(self):
        """文件模式 fallback：config.yaml 的 kids 块进入合并配置（含 enabled）。"""
        kids = CONFIG.get("kids")
        assert isinstance(kids, dict), "config.yaml 应含顶层 kids 块"
        assert "enabled" in kids, "kids 块应含 enabled 开关（与 #5 合并语义）"
        assert kids["enabled"] is False, "默认模板不开儿童模式"
