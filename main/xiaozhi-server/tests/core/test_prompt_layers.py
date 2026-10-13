"""缝 1 测试：system prompt 五层结构（L1→L5）。

以 fake LLM provider 挂进 ConnectionHandler，跑一轮真实 chat()，在 fake
LLM 收到的 dialogue 上断言 system prompt 的分层边界与顺序。
provider 接口契约先例：tests/test_llm.py。

分层契约（ADR-0001）：
    L1 静态人设/安全 → L2 档案 → L3 长期记忆 → L4 滚动摘要 都在 system
    消息内，以 <layer-N-*> 标签为边界；L5 对话窗口是 system 之后的消息列表。

运行要求：CWD 必须在 main/xiaozhi-server（prompt 模板按相对路径加载，
与 ``make test-python`` 的运行方式一致）。
"""
from __future__ import annotations

import asyncio
import copy
import queue
import threading
import uuid

import pytest

from tests.conftest import CONFIG

LAYER_TAGS = {
    1: ("layer-1-persona", "静态人设/安全"),
    2: ("layer-2-profile", "档案"),
    3: ("layer-3-memory", "长期记忆"),
    4: ("layer-4-summary", "滚动摘要"),
}
MEMORY_TEXT = "用户喜欢猫"


class FakeLLM:
    """按 core/providers/llm/base.py 契约记录收到的 dialogue。"""

    def __init__(self):
        self.calls = []

    def response(self, session_id, dialogue):
        self.calls.append(dialogue)
        yield "好的呀。"


class FakeMemory:
    async def query_memory(self, query):
        return MEMORY_TEXT


class FakeTTS:
    def __init__(self):
        self.tts_text_queue = queue.Queue()
        self.stored = []

    def store_tts_text(self, sentence_id, text):
        self.stored.append((sentence_id, text))


@pytest.fixture()
def fake_llm_conn():
    """构造挂了 fake LLM/Memory/TTS 的 ConnectionHandler 并跑一轮对话。

    yields (conn, fake_llm)；结束后停掉辅助事件循环线程。
    """
    from core.connection import ConnectionHandler

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    llm = FakeLLM()
    conn = ConnectionHandler(
        copy.deepcopy(CONFIG),
        _vad=None,
        _asr=None,
        _llm=llm,
        _memory=FakeMemory(),
        _intent=None,
    )
    conn.loop = loop
    conn.tts = FakeTTS()
    conn.features = {"emoji": False}  # 跳过表情协程，测试只关心 prompt 结构
    # 每个测试独立 device_id，避免 device_prompt 全局缓存串台
    conn.device_id = f"prompt-layer-test-{uuid.uuid4().hex}"

    # 走真实装配链：增强提示词（Jinja2 渲染 agent-base-prompt.txt）
    conn._init_prompt_enhancement()
    # 走真实对话链：chat() 会把分层 system prompt 组装进 LLM 请求
    conn.chat("你好")

    yield conn, llm

    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=5)
    loop.close()


def _system_content(fake_llm) -> str:
    assert fake_llm.calls, "fake LLM 未收到任何请求（chat() 未走到 LLM 调用）"
    msgs = fake_llm.calls[0]
    assert msgs[0]["role"] == "system", "第一条消息应是 system"
    return msgs[0]["content"]


def test_system_prompt_has_layers_in_order(fake_llm_conn):
    """L1→L4 边界标记在 system prompt 内按固定顺序出现。"""
    _, llm = fake_llm_conn
    content = _system_content(llm)

    opens = [f"<{tag}>" for tag, _ in LAYER_TAGS.values()]
    closes = [f"</{tag}>" for tag, _ in LAYER_TAGS.values()]
    open_pos = [content.index(o) for o in opens]  # 缺任一标记即 ValueError → 失败
    close_pos = [content.index(c) for c in closes]

    assert open_pos == sorted(open_pos), "L1→L4 开标记必须按层序出现"
    assert close_pos == sorted(close_pos), "L1→L4 闭标记必须按层序出现"
    # 每层闭合先于下一层开启：边界不交叉
    for i in range(3):
        assert close_pos[i] < open_pos[i + 1], f"第 {i + 1} 层边界与下一层交叉"


def test_memory_lands_inside_layer3(fake_llm_conn):
    """当轮记忆注入应落在 L3 边界内（现状等价物：<memory> 标签替换）。"""
    _, llm = fake_llm_conn
    content = _system_content(llm)
    l3_open, l3_close = f"<{LAYER_TAGS[3][0]}>", f"</{LAYER_TAGS[3][0]}>"
    assert content.index(l3_open) < content.index(MEMORY_TEXT) < content.index(l3_close)


def test_layer1_holds_static_persona_and_safety(fake_llm_conn):
    """L1 应包含现状等价物：角色设定（config prompt）与安全合规段。"""
    _, llm = fake_llm_conn
    content = _system_content(llm)
    l1_open, l1_close = f"<{LAYER_TAGS[1][0]}>", f"</{LAYER_TAGS[1][0]}>"
    l1 = content[content.index(l1_open) : content.index(l1_close)]

    assert "<identity>" in l1, "角色设定（<identity>）应在 L1 内"
    assert "<safety_compliance>" in l1, "安全合规段应在 L1 内"


def test_layer5_window_follows_system_message(fake_llm_conn):
    """L5 对话窗口：本轮 user 消息应在 system 消息之后、assistant 回复之前。"""
    _, llm = fake_llm_conn
    msgs = llm.calls[0]
    roles = [m["role"] for m in msgs]

    assert roles[0] == "system"
    assert "user" in roles[1:], "窗口应包含本轮 user 消息"
    user_idx = roles.index("user", 1)
    assert {"role": "user", "content": "你好"} == msgs[user_idx]
