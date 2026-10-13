"""缝 1 测试：孩子档案渲染进 L2（工单 #6）。

以 fake LLM provider 挂进 ConnectionHandler，跑真实 chat()，在 fake LLM
收到的 system prompt 上断言：档案文案落在 <layer-2-profile> 边界内、
年龄段随生日每轮重算（过生日升档）、生日缺失/非法退化为无年龄分档。
provider 接口与装配链先例：tests/core/test_prompt_layers.py。

档案数据通道（两模式同一读取代码 self.config["kids"]）：
- 文件模式：config.yaml 顶层 kids 块（fallback）
- API 模式：manager-api Agent.kidProfile JSON 经 per-agent 下发
  （tests/core/test_kids_config.py 覆盖消费点）
"""
from __future__ import annotations

import asyncio
import copy
import queue
import threading
import uuid
from datetime import date

import pytest

import core.utils.kids_profile as kids_profile_module
from tests.conftest import CONFIG

KIDS_PROFILE = {
    "enabled": True,
    "nickname": "小豆",
    "birth_ym": "2019-05",
    "personality": "好奇心重",
    "hobbies": "恐龙",
    "instructions": "睡前不讲吓人的故事",
    "taboos": ["不聊鬼故事"],
}


class FakeLLM:
    def __init__(self):
        self.calls = []

    def response(self, session_id, dialogue):
        self.calls.append(dialogue)
        yield "好的呀。"


class FakeMemory:
    async def query_memory(self, query):
        return ""


class FakeTTS:
    def __init__(self):
        self.tts_text_queue = queue.Queue()

    def store_tts_text(self, sentence_id, text):
        pass


def _make_conn(kids: dict | None):
    """构造挂了 fake 组件的 ConnectionHandler（不预跑对话）。"""
    from core.connection import ConnectionHandler

    config = copy.deepcopy(CONFIG)
    if kids is None:
        config.pop("kids", None)
    else:
        config["kids"] = copy.deepcopy(kids)

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    llm = FakeLLM()
    conn = ConnectionHandler(
        config,
        _vad=None,
        _asr=None,
        _llm=llm,
        _memory=FakeMemory(),
        _intent=None,
    )
    conn.loop = loop
    conn.tts = FakeTTS()
    conn.features = {"emoji": False}
    conn.device_id = f"kids-l2-test-{uuid.uuid4().hex}"
    conn._init_prompt_enhancement()
    return conn, llm, (loop, loop_thread)


def _teardown(conn, loop, loop_thread):
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=5)
    loop.close()


def _system_content(llm, call_idx=-1) -> str:
    msgs = llm.calls[call_idx]
    assert msgs[0]["role"] == "system"
    return msgs[0]["content"]


class TestProfileLandsInLayer2:
    def test_full_profile_inside_layer2_boundaries(self):
        conn, llm, loops = _make_conn(KIDS_PROFILE)
        try:
            conn.chat("你好")
            content = _system_content(llm)
            l2_open = content.index("<layer-2-profile>")
            l2_close = content.index("</layer-2-profile>")
            for fragment in (
                "【你陪伴的孩子】",
                "称呼：小豆（平时就这么叫他）",
                "性格：好奇心重",
                "【家长嘱托，记在心里】",
                "【家长定的禁忌，必须做到】",
                "- 不聊鬼故事",
            ):
                assert l2_open < content.index(fragment) < l2_close
        finally:
            _teardown(conn, *loops)

    def test_no_kids_config_leaves_layer2_empty(self):
        conn, llm, loops = _make_conn(None)
        try:
            conn.chat("你好")
            content = _system_content(llm)
            assert "【你陪伴的孩子】" not in content
        finally:
            _teardown(conn, *loops)


class TestAgeBandRecalculatedPerTurn:
    def test_birthday_upgrades_band_within_same_connection(self, monkeypatch):
        """同一连接内过生日：下一轮 system prompt 自动升档（每轮重算）。"""
        conn, llm, loops = _make_conn(KIDS_PROFILE)
        try:
            monkeypatch.setattr(
                kids_profile_module, "_today", lambda: date(2025, 4, 15)
            )
            conn.chat("你好")
            before = _system_content(llm, 0)
            assert "按3-5 岁孩子的理解和话题深度对话" in before

            # 时间推进到生日月之后（2019-05 出生 → 2025-05 满 6 岁升档）
            monkeypatch.setattr(
                kids_profile_module, "_today", lambda: date(2025, 5, 2)
            )
            conn.chat("后来呢")
            after = _system_content(llm, -1)
            assert "按6-8 岁孩子的理解和话题深度对话" in after
            assert "按3-5 岁孩子的理解和话题深度对话" not in after
        finally:
            _teardown(conn, *loops)

    def test_invalid_birth_degrades_without_crash(self):
        conn, llm, loops = _make_conn({**KIDS_PROFILE, "birth_ym": "2019-13"})
        try:
            conn.chat("你好")  # 不应抛出
            content = _system_content(llm)
            assert "称呼：小豆" in content
            assert "年龄：" not in content
        finally:
            _teardown(conn, *loops)
