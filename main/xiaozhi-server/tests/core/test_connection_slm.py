"""SLM 槽位接通测试（工单 #2）。

被测行为：智控台 Agent 的 slmModelId 随连接下发后（selected_module.SLM
指向 LLM 配置块中的一个条目），Python 服务端消费该键，为连接生成一个
独立于主对话模型的小模型实例并挂到 conn.slm。

外部边界：
- 配置（文件模式 config.yaml 形状 / API 模式 private_config 形状）进
- conn.slm 实例（由 core.utils.llm.create_instance 工厂产出）出

create_instance 依赖进程 CWD 与磁盘上的 provider 目录，测试里统一
monkeypatch 成记录调用的 fake，只验证「配置 → 工厂调用 → 挂载」。
"""
from __future__ import annotations

import asyncio
import copy

import pytest

import core.connection as connection_module
from core.connection import ConnectionHandler
from tests.conftest import CONFIG

SLM_SECTION = "XiaoZhiSLM"
SLM_CONFIG = {
    "type": "openai",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model_name": "qwen-flash",
    "api_key": "slm-test-key",
}


def _base_config() -> dict:
    """文件模式形状的连接配置：conftest CONFIG 深拷贝后裁剪。"""
    config = copy.deepcopy(CONFIG)
    config["selected_module"] = copy.deepcopy(config.get("selected_module", {}))
    config["LLM"] = copy.deepcopy(config.get("LLM", {}))
    return config


def _make_handler(config: dict) -> ConnectionHandler:
    return ConnectionHandler(config, None, None, None, None, None)


@pytest.fixture()
def fake_factory(monkeypatch):
    """替身工厂：记录调用并返回可识别的 sentinel 实例。"""
    calls: list[tuple] = []
    sentinel = object()

    def _fake_create_instance(class_name, *args, **kwargs):
        calls.append((class_name, args, kwargs))
        return sentinel

    import core.utils.llm as llm_utils

    monkeypatch.setattr(llm_utils, "create_instance", _fake_create_instance)
    return calls, sentinel


class TestSlmSlotCreatesInstance:
    def test_file_mode_slm_slot_creates_independent_instance(self, fake_factory):
        """缝 2：含 SLM 槽位的配置 → 独立小模型实例挂到连接。"""
        calls, sentinel = fake_factory
        config = _base_config()
        config["selected_module"]["SLM"] = SLM_SECTION
        config["LLM"][SLM_SECTION] = copy.deepcopy(SLM_CONFIG)

        handler = _make_handler(config)
        main_llm = object()
        handler.llm = main_llm

        handler._initialize_slm()

        assert handler.slm is sentinel
        assert handler.slm is not main_llm
        # 工厂收到 SLM 条目的 type 与完整配置（与 intent_llm 第二实例同模式）
        assert calls == [("openai", (copy.deepcopy(SLM_CONFIG),), {})]

    def test_private_config_slm_key_survives_consumption(self, fake_factory, monkeypatch):
        """API 模式：manager-api 下发的 selected_module.SLM 不被逐键拷贝丢弃。"""
        calls, sentinel = fake_factory
        config = _base_config()
        config["read_config_from_api"] = True

        handler = _make_handler(config)
        handler.headers = {"device-id": "test-device"}

        private_config = {
            "LLM": {
                "main-llm-id": {"type": "openai", "model_name": "qwen-max"},
                "slm-model-id": copy.deepcopy(SLM_CONFIG),
            },
            "selected_module": {"LLM": "main-llm-id", "SLM": "slm-model-id"},
        }

        async def _fake_get_private_config(_config, *_args, **_kwargs):
            return copy.deepcopy(private_config)

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

        # 键被消费进连接配置，且随后的初始化能据此产出实例
        assert handler.config["selected_module"]["SLM"] == "slm-model-id"
        handler._initialize_slm()
        assert handler.slm is sentinel
        assert calls[0][0] == "openai"


class TestSlmDegradesGracefully:
    def test_no_slm_slot_leaves_connection_untouched(self, fake_factory):
        """未配置 SLM：conn.slm 保持 None，不触发工厂，不影响主链路。"""
        calls, _sentinel = fake_factory
        config = _base_config()
        assert "SLM" not in config["selected_module"]

        handler = _make_handler(config)
        main_llm = object()
        handler.llm = main_llm

        handler._initialize_slm()

        assert handler.slm is None
        assert calls == []
        assert handler.llm is main_llm

    def test_dangling_slm_reference_degrades_to_none(self, fake_factory):
        """SLM 指向的 LLM 条目缺失：告警退化，不抛异常。"""
        calls, _sentinel = fake_factory
        config = _base_config()
        config["selected_module"]["SLM"] = "no-such-llm-section"

        handler = _make_handler(config)

        handler._initialize_slm()  # 不应抛出

        assert handler.slm is None
        assert calls == []

    def test_slm_factory_failure_does_not_break_connection(self, monkeypatch):
        """工厂抛异常：self.slm 保持 None，异常被吞掉（主对话链路不受影响）。"""
        config = _base_config()
        config["selected_module"]["SLM"] = SLM_SECTION
        config["LLM"][SLM_SECTION] = copy.deepcopy(SLM_CONFIG)

        handler = _make_handler(config)

        import core.utils.llm as llm_utils

        def _boom(_class_name, *_args, **_kwargs):
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr(llm_utils, "create_instance", _boom)

        handler._initialize_slm()  # 不应抛出

        assert handler.slm is None
