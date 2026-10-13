"""缝 1 测试：儿童记忆与摘要对齐 L3/L4（工单 #7）。

以 fake 主 LLM + 真 mem_kids provider（fake SLM）挂进 ConnectionHandler，
跑真实 chat()，断言：
- L3 长期记忆注入 <memory>（layer-3 边界内）、L4 滚动摘要注入 <summary>
  （layer-4 边界内）
- 回合收尾触发后台趟（conn.slm 抽取+压缩），敏感信息不入长期记忆
- 非儿童 memory provider（无 get_rolling_summary/on_turn_end）行为不变

先例：tests/core/test_prompt_layers.py（连接级 fake provider 模式）、
tests/core/test_connection_slm.py。
运行要求：CWD 必须在 main/xiaozhi-server。
"""
from __future__ import annotations

import asyncio
import copy
import json
import queue
import threading
import time
import uuid

import pytest
import yaml

from tests.conftest import CONFIG

from core.providers.memory.mem_kids.mem_kids import COMPACT_TURNS, MemoryProvider


class FakeLLM:
    """按 core/providers/llm/base.py 契约记录收到的 dialogue。"""

    def __init__(self):
        self.calls = []

    def response(self, session_id, dialogue):
        self.calls.append(dialogue)
        yield "好呀。"


class FakeSLM:
    """按 response_no_stream 契约回放脚本响应。"""

    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)

    def response_no_stream(self, system_prompt, user_prompt, **kwargs):
        self.calls.append((system_prompt, user_prompt))
        item = self._responses.pop(0)
        return item(system_prompt, user_prompt) if callable(item) else item


class FakeTTS:
    def __init__(self):
        self.tts_text_queue = queue.Queue()
        self.stored = []

    def store_tts_text(self, sentence_id, text):
        self.stored.append((sentence_id, text))


class PlainMemory:
    """非儿童 provider：只有 base 契约方法。"""

    async def query_memory(self, query):
        return "用户喜欢猫"


def _make_kids_provider(tmp_path, slm):
    p = MemoryProvider({}, None)
    p.memory_path = str(tmp_path / ".memory_kids.yaml")
    p.init_memory(role_id=f"kid-{uuid.uuid4().hex}", llm=slm)
    return p


def _make_conn(memory):
    from core.connection import ConnectionHandler

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    conn = ConnectionHandler(
        copy.deepcopy(CONFIG), _vad=None, _asr=None, _llm=FakeLLM(),
        _memory=memory, _intent=None,
    )
    conn.loop = loop
    conn.tts = FakeTTS()
    conn.features = {"emoji": False}
    conn.device_id = f"kids-mem-test-{uuid.uuid4().hex}"
    conn._init_prompt_enhancement()
    return conn, loop


def _teardown(conn, loop):
    loop.call_soon_threadsafe(loop.stop)
    conn.executor.shutdown(wait=False)


def _system_content(conn):
    llm = conn.llm
    assert llm.calls, "fake LLM 未收到任何请求"
    msgs = llm.calls[0]
    assert msgs[0]["role"] == "system"
    return msgs[0]["content"]


def test_chat_injects_kids_memory_and_summary_into_layers(tmp_path):
    """L3 条目落 layer-3 内、L4 摘要落 layer-4 内，顺序不交叉。"""
    provider = _make_kids_provider(tmp_path, slm=None)
    store = {provider.role_id: {
        "entries": [{"id": 1, "ts": 100, "text": "喜欢恐龙"}],
        "summary": "孩子喜欢恐龙，情绪开心。",
    }}
    (tmp_path / ".memory_kids.yaml").write_text(
        yaml.safe_dump(store, allow_unicode=True), encoding="utf-8")
    provider.load_memory(None)

    conn, loop = _make_conn(provider)
    try:
        conn.chat("你好")
        content = _system_content(conn)

        assert content.index("<layer-3-memory>") < content.index("【小智记住的事】")
        assert content.index("【小智记住的事】") < content.index("</layer-3-memory>")
        assert content.index("</layer-3-memory>") < content.index("【前面聊过的】")
        assert content.index("【前面聊过的】") < content.index("</layer-4-summary>")
        assert "喜欢恐龙" in content
    finally:
        _teardown(conn, loop)


def test_turn_end_extracts_and_compacts_via_slm(tmp_path):
    """回合收尾后台趟：第 20 轮触发抽取+压缩；敏感信息不入长期记忆。"""
    extract_ops = json.dumps(
        [
            {"op": "add", "text": "家住幸福路12号"},
            {"op": "add", "text": "电话13812345678"},
            {"op": "add", "text": "喜欢恐龙"},
        ],
        ensure_ascii=False,
    )
    slm = FakeSLM([extract_ops, "孩子喜欢恐龙，正聊恐龙话题，情绪开心。"])
    provider = _make_kids_provider(tmp_path, slm=slm)
    provider._turn_count = COMPACT_TURNS - 1

    conn, loop = _make_conn(provider)
    try:
        conn.chat("我家住幸福路12号，我喜欢恐龙")

        deadline = time.time() + 5
        while time.time() < deadline and len(slm.calls) < 2:
            time.sleep(0.02)
        assert len(slm.calls) == 2, "回合收尾未触发抽取+压缩后台趟"

        texts = [e["text"] for e in provider.list_memories()]
        assert texts == ["喜欢恐龙"], "住址/电话不得进入长期记忆"
        assert provider.get_rolling_summary() == "【前面聊过的】\n孩子喜欢恐龙，正聊恐龙话题，情绪开心。"
    finally:
        _teardown(conn, loop)


def test_plain_memory_provider_leaves_l4_empty(tmp_path):
    """非儿童 provider：无摘要来源，<summary> 保持模板空标签，chat 正常。"""
    conn, loop = _make_conn(PlainMemory())
    try:
        conn.chat("你好")
        content = _system_content(conn)
        assert "<summary>\n</summary>" in content
        assert "【前面聊过的】" not in content
        assert "用户喜欢猫" in content  # L3 现状等价物照常注入
    finally:
        _teardown(conn, loop)


class RecordingMemory:
    """记录 init_memory/set_llm 收到的实例，探测 _initialize_memory 接线。"""

    def __init__(self):
        self.llm = None
        self.init_args = None

    def init_memory(self, role_id, llm, **kwargs):
        self.init_args = (role_id, kwargs)
        self.llm = llm

    def set_llm(self, llm):
        self.llm = llm


def _kids_config():
    config = copy.deepcopy(CONFIG)
    config["selected_module"] = dict(config.get("selected_module", {}))
    config["selected_module"]["Memory"] = "mem_kids"
    config["Memory"] = dict(config.get("Memory", {}))
    config["Memory"]["mem_kids"] = {"type": "mem_kids"}
    return config


def test_initialize_memory_binds_kids_provider_to_slm():
    """mem_kids 配置下，抽取/压缩模型优先绑 conn.slm（工单 #2 槽位）。"""
    from core.connection import ConnectionHandler

    conn = ConnectionHandler(_kids_config(), None, None, None, None, None)
    memory = RecordingMemory()
    conn.memory = memory
    conn.llm = object()
    conn.slm = object()

    conn._initialize_memory()

    assert memory.llm is conn.slm


def test_initialize_memory_kids_degrades_to_main_llm_without_slm():
    """未配置 SLM：退化绑主 LLM，不抛异常。"""
    from core.connection import ConnectionHandler

    conn = ConnectionHandler(_kids_config(), None, None, None, None, None)
    memory = RecordingMemory()
    conn.memory = memory
    conn.llm = object()
    conn.slm = None

    conn._initialize_memory()

    assert memory.llm is conn.llm
