"""TTS 适配器音色选定测试（儿童陪伴工单 #4：cosyvoice-v2 童声 longhuhu）。

覆盖两条引擎路径的音色下发行为：
- alibl_stream（dashscope CosyVoice 双向流式）：seam = start_session 发出的
  run-task 线上报文 —— 模型/音色必须原样到达 dashscope。
- aliyun（sambert 非流式 NLS）：seam = text_to_speak 发出的 HTTP 请求体。

预期值来源（独立事实源，勿从实现反推）：
- 小布参考设计 core/src/xb_core.c：cosyvoice-v2 + longhuhu + PlainText + pcm，
  v3/v3.5 引擎对 longhuhu 一律 418，模型必须同为 v2。
- per-agent 通道：manager-api 把 Timbre 表音色注入 TTS configJson 的
  private_voice，覆盖共享配置的 voice（ConfigServiceImpl.buildModuleConfig）。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from core.providers.tts import alibl_stream, aliyun

# 儿童模式部署形态：整台设备即儿童 Agent，音色直接配在 TTS 配置块。
KIDS_TTS_CONFIG = {
    "api_key": "test-api-key",
    "model": "cosyvoice-v2",
    "voice": "longhuhu",
}


class _FakeWebSocket:
    """记录 send 出的报文，recv 永远挂起（等 close 取消监听 task）。"""

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        await asyncio.Event().wait()

    async def close(self):
        pass


def _start_cosyvoice_session(monkeypatch, config: dict) -> list[dict]:
    """构造 alibl_stream provider 并跑一次 start_session，返回发出的报文列表。"""
    provider = alibl_stream.TTSProvider(config, True)
    provider.conn = SimpleNamespace(sample_rate=16000)
    fake_ws = _FakeWebSocket()

    async def _fake_connect(*_args, **_kwargs):
        return fake_ws

    monkeypatch.setattr(alibl_stream.websockets, "connect", _fake_connect)

    async def _run():
        await provider.start_session("test-session")
        await provider.close()  # 取消监听 task，干净收尾

    asyncio.run(_run())
    return [json.loads(m) for m in fake_ws.sent]


def _sambert_request_body(monkeypatch, config: dict) -> dict:
    """构造 aliyun(sambert) provider 跑一次 text_to_speak，返回 POST 请求体。"""
    provider = aliyun.TTSProvider(config, True)
    provider.conn = SimpleNamespace(sample_rate=16000)
    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200
        headers = {"Content-Type": "audio/wav"}
        content = b"fake-audio"

    def _fake_post(url, body, **_kwargs):
        captured["url"] = url
        captured["body"] = json.loads(body)
        return _FakeResponse()

    monkeypatch.setattr(aliyun.requests, "post", _fake_post)
    asyncio.run(provider.text_to_speak("你好呀", None))
    return captured["body"]


# ---------------------------------------------------------------------------
# cosyvoice（alibl_stream）路径
# ---------------------------------------------------------------------------


def test_cosyvoice_run_task_carries_configured_model_and_kids_voice(monkeypatch):
    """儿童配置（cosyvoice-v2 + longhuhu）必须原样进 run-task 报文。"""
    # Act
    messages = _start_cosyvoice_session(monkeypatch, KIDS_TTS_CONFIG)

    # Assert
    assert messages, "start_session 未发出任何报文"
    run_task = messages[0]
    assert run_task["header"]["action"] == "run-task"
    assert run_task["header"]["streaming"] == "duplex"
    payload = run_task["payload"]
    assert payload["task_group"] == "audio"
    assert payload["task"] == "tts"
    assert payload["function"] == "SpeechSynthesizer"
    assert payload["model"] == "cosyvoice-v2", "longhuhu 仅 v2 可用，模型错会 418"
    parameters = payload["parameters"]
    assert parameters["voice"] == "longhuhu"
    assert parameters["text_type"] == "PlainText"
    assert parameters["format"] == "pcm"


def test_cosyvoice_private_voice_overrides_shared_voice_in_run_task(monkeypatch):
    """per-agent 音色（private_voice）必须覆盖共享 voice 进 run-task。"""
    # Arrange：共享配置是成人音色，Agent 绑定童声
    config = {
        "api_key": "test-api-key",
        "model": "cosyvoice-v2",
        "voice": "longcheng_v2",
        "private_voice": "longhuhu",
    }

    # Act
    messages = _start_cosyvoice_session(monkeypatch, config)

    # Assert
    parameters = messages[0]["payload"]["parameters"]
    assert parameters["voice"] == "longhuhu", "儿童 Agent 不允许回落到成人音色"


def test_cosyvoice_defaults_unchanged(monkeypatch):
    """未显式配置时默认仍是 cosyvoice-v2 / longxiaochun_v2（锁既有行为）。"""
    # Act
    messages = _start_cosyvoice_session(monkeypatch, {"api_key": "test-api-key"})

    # Assert
    payload = messages[0]["payload"]
    assert payload["model"] == "cosyvoice-v2"
    assert payload["parameters"]["voice"] == "longxiaochun_v2"


# ---------------------------------------------------------------------------
# sambert（aliyun）路径：既有音色不受儿童模式影响
# ---------------------------------------------------------------------------


def test_sambert_request_carries_default_voice_xiaoyun(monkeypatch):
    """sambert 默认音色 xiaoyun 保持不变。"""
    # Act
    body = _sambert_request_body(
        monkeypatch, {"appkey": "test-appkey", "token": "test-token"}
    )

    # Assert
    assert body["voice"] == "xiaoyun"
    assert body["appkey"] == "test-appkey"


def test_sambert_private_voice_overrides_shared_voice(monkeypatch):
    """per-agent private_voice 通道对 sambert 同样生效（音色下发是通用机制）。"""
    # Arrange
    config = {
        "appkey": "test-appkey",
        "token": "test-token",
        "voice": "xiaoyun",
        "private_voice": "longhuhu",
    }

    # Act
    body = _sambert_request_body(monkeypatch, config)

    # Assert
    assert body["voice"] == "longhuhu"
