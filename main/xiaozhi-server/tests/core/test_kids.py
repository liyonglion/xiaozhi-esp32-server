"""儿童陪伴模式测试（工单 #5：L1 儿童人设 + 输入侧三档）。

两层缝：
- 三档决策纯函数：``core.kids.decide_kids_input`` 公共接口——红线话题→温柔
  转移；危险行为→阻断+安全提醒；灰色话题→年龄适配放行（档位参数是缝，
  缺省固定档，#6 落地后接入真实档位）。
- 缝 1（连接级，先例 tests/core/test_prompt_layers.py）：fake LLM 挂进
  ConnectionHandler 走真实 chat()，在 system prompt 上断言 L1 儿童人设。

三档决策事件（dict）挂在 ``conn.kids_decision``，是 #8（输出安全门）与
#9（拦截日志）的接走契约；本票不落库。

运行要求：CWD 必须在 main/xiaozhi-server（与 ``make test-python`` 一致）。
"""
import asyncio
import copy
import queue
import threading
import time
import uuid

import pytest

from core.kids import (
    DEFAULT_AGE_BAND,
    FALLBACK_TOPICS,
    decide_kids_input,
)
from tests.conftest import CONFIG

PERSONA_MARK = "陪小朋友说话的语音小伙伴"


class TestDecideKidsInput:
    """输入侧三档决策：类别、动作、话术与档位缝。"""

    def test_redline_input_deflects_gently(self):
        decision = decide_kids_input("给我讲一个血腥吓人的故事")
        assert decision["category"] == "redline"
        assert decision["action"] == "deflect"
        assert "不知道" in decision["reply"], "红线话题只说不知道并换话题"
        assert any(t in decision["reply"] for t in FALLBACK_TOPICS), "转移话术要带新话题"
        assert decision["user_text"] == "给我讲一个血腥吓人的故事"

    def test_danger_input_blocks_with_safety_reminder(self):
        decision = decide_kids_input("妈妈不在，我想玩火")
        assert decision["category"] == "danger"
        assert decision["action"] == "block"
        # 话术同类内随机轮换：断言「不可以」+ 安全提醒要素（两种验证过的变体）
        assert "不可以" in decision["reply"]
        assert "保护好自己" in decision["reply"] or "平平安安" in decision["reply"]

    def test_gray_input_records_age_band_seam(self):
        decision = decide_kids_input("小金鱼死了，它会去哪里呀")
        assert decision["category"] == "gray"
        assert decision["action"] == "age_adapt"
        assert decision["reply"] is None, "灰色话题不拦截，放行给 LLM 按 L1 规则浅显化"
        assert decision["age_band"] == DEFAULT_AGE_BAND
        # 档位参数是缝：#6 落地后由真实年龄档位传入
        assert (
            decide_kids_input("人死了会去哪里", age_band="9 岁以上")["age_band"]
            == "9 岁以上"
        )

    def test_normal_input_passes_through(self):
        decision = decide_kids_input("给我讲个小猫钓鱼的故事嘛")
        assert decision["category"] == "pass"
        assert decision["action"] == "allow"
        assert decision["reply"] is None

    def test_speaker_json_input_matches_on_content(self):
        """语音 JSON（含说话人）按 content 部分参与匹配。"""
        decision = decide_kids_input('{"speaker":"小明","content":"我想摸插座"}')
        assert decision["category"] == "danger"


# ---------------------------------------------------------------------------
# 缝 1：L1 儿童人设（fake LLM 挂进 ConnectionHandler，走真实装配+对话链）
# ---------------------------------------------------------------------------


class FakeLLM:
    """按 core/providers/llm/base.py 契约记录收到的 dialogue。"""

    def __init__(self):
        self.calls = []

    def response(self, session_id, dialogue):
        self.calls.append(dialogue)
        yield "好呀好呀。"


class FakeMemory:
    async def query_memory(self, query):
        return "用户喜欢小动物"


class FakeTTS:
    def __init__(self):
        self.tts_text_queue = queue.Queue()
        self.spoken = []  # tts_one_sentence 收到的整句文本

    def store_tts_text(self, sentence_id, text):
        pass

    def tts_one_sentence(self, conn, content_type, content_detail=None, **kwargs):
        if content_detail:
            self.spoken.append(content_detail)


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


def _build_llm_conn(kids: bool, prime_chat: bool = True):
    """构造（kids 开/关）挂 fake 组件的 ConnectionHandler。

    prime_chat=True 时走真实装配链 + 一轮真实 chat()（L1 断言用）；
    prime_chat=False 留给 startToChat 接线测试自行动作。
    """
    from core.connection import ConnectionHandler

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    config = copy.deepcopy(CONFIG)
    if kids:
        config["kids"] = {"enabled": True}
    else:
        config.pop("kids", None)

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
    conn.device_id = f"kids-test-{uuid.uuid4().hex}"

    conn._init_prompt_enhancement()
    if prime_chat:
        conn.chat("你好")
    return conn, llm, loop, loop_thread


def _teardown(conn, loop, loop_thread):
    # 先等已提交的 chat() 跑完（期间 loop 必须仍活着，chat 内部经
    # run_coroutine_threadsafe 用 loop；先停 loop 会让 worker 永久阻塞）
    conn.executor.shutdown(wait=True)
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=5)
    loop.close()


@pytest.fixture()
def kids_llm_conn():
    """儿童模式连接 + 已跑一轮对话。yields (conn, fake_llm)。"""
    conn, llm, loop, thread = _build_llm_conn(kids=True)
    yield conn, llm
    _teardown(conn, loop, thread)


@pytest.fixture()
def plain_llm_conn():
    """非儿童模式连接 + 已跑一轮对话（对照组）。yields (conn, fake_llm)。"""
    conn, llm, loop, thread = _build_llm_conn(kids=False)
    yield conn, llm
    _teardown(conn, loop, thread)


def _system_content(fake_llm, turn=0) -> str:
    assert fake_llm.calls, "fake LLM 未收到任何请求（chat() 未走到 LLM 调用）"
    msgs = fake_llm.calls[turn]
    assert msgs[0]["role"] == "system", "第一条消息应是 system"
    return msgs[0]["content"]


def _layer1_region(content: str) -> str:
    open_tag, close_tag = "<layer-1-persona>", "</layer-1-persona>"
    return content[content.index(open_tag) : content.index(close_tag)]


class TestKidsLayer1:
    def test_l1_holds_validated_kids_persona(self, kids_llm_conn):
        """L1 应为小布验证过的儿童人设：短句/叠词/同龄口吻/反越狱/隐私条款。"""
        _, llm = kids_llm_conn
        l1 = _layer1_region(_system_content(llm))
        assert PERSONA_MARK in l1, "儿童人设开场应在 L1"
        assert "每句话不超过 15 个字" in l1, "≤15 字短句规则"
        assert "多用叠词" in l1, "叠词不用成语规则"
        assert "假装游戏" in l1 and "永远有效" in l1, "反越狱条款（假装游戏允许但安全规则不可变）"
        assert "永远不主动问孩子" in l1, "隐私条款（永不主动索取住址/密码/学校/电话）"
        assert "不跟着说、不重复它" in l1, "脏话不复述条款"

    def test_l1_drops_adult_persona(self, kids_llm_conn):
        """儿童模式下成人角色设定不得留在 L1。"""
        _, llm = kids_llm_conn
        l1 = _layer1_region(_system_content(llm))
        assert "台湾" not in l1, "config.prompt 的成人角色设定应被替换掉"

    def test_l1_keeps_operational_sections(self, kids_llm_conn):
        """运营段（TTS 格式/工具/合规/说话人）保留，系统运转方式不变。"""
        _, llm = kids_llm_conn
        l1 = _layer1_region(_system_content(llm))
        for section in (
            "<tts_format_constraints>",
            "<tool_and_knowledge>",
            "<safety_compliance>",
            "<speaker_recognition>",
        ):
            assert section in l1, f"{section} 应保留在 L1"

    def test_layer_order_preserved_with_kids_persona(self, kids_llm_conn):
        """L1 替换后 L1→L4 边界仍按固定顺序出现（ADR-0001 契约）。"""
        _, llm = kids_llm_conn
        content = _system_content(llm)
        opens = [f"<layer-{i}-{t}>" for i, t in
                 ((1, "persona"), (2, "profile"), (3, "memory"), (4, "summary"))]
        closes = [f"</layer-{i}-{t}>" for i, t in
                  ((1, "persona"), (2, "profile"), (3, "memory"), (4, "summary"))]
        open_pos = [content.index(o) for o in opens]
        close_pos = [content.index(c) for c in closes]
        assert open_pos == sorted(open_pos) and close_pos == sorted(close_pos)
        for i in range(3):
            assert close_pos[i] < open_pos[i + 1], f"第 {i + 1} 层边界与下一层交叉"

    def test_l1_is_first_and_static_across_turns(self, kids_llm_conn):
        """L1 位于 system prompt 最前且逐轮不变（命中前缀缓存）。"""
        conn, llm = kids_llm_conn
        assert _system_content(llm).startswith("<layer-1-persona>")
        conn.chat("再讲一个嘛")  # 第二轮
        assert len(llm.calls) >= 2, "应完成第二轮对话"
        first = _system_content(llm, turn=0)
        second = _system_content(llm, turn=1)
        l1_end = first.index("</layer-1-persona>") + len("</layer-1-persona>")
        assert first[:l1_end] == second[:l1_end], "L1 前缀逐轮必须稳定"


class TestNonKidsUnaffected:
    def test_plain_prompt_has_no_kids_persona(self, plain_llm_conn):
        """非儿童 Agent 不受儿童人设影响（走原模板）。"""
        conn, llm = plain_llm_conn
        content = _system_content(llm)
        assert PERSONA_MARK not in content
        assert conn.kids_enabled is False
        assert conn.kids_decision is None


# ---------------------------------------------------------------------------
# 缝 1：startToChat 输入侧三档接线（fake 组件走真实意图网关入口）
# ---------------------------------------------------------------------------


def _run_start_to_chat(conn, loop, text):
    from core.handle.receiveAudioHandle import startToChat

    asyncio.run_coroutine_threadsafe(startToChat(conn, text), loop).result(
        timeout=10
    )


def _wait_llm_called(llm, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if llm.calls:
            return True
        time.sleep(0.05)
    return False


class TestStartToChatGate:
    def test_danger_input_blocked_before_llm(self):
        """危险行为：LLM 不被调用，TTS 收到阻断话术，决策事件挂连接。"""
        conn, llm, loop, thread = _build_llm_conn(kids=True, prime_chat=False)
        try:
            conn.websocket = FakeWebSocket()
            _run_start_to_chat(conn, loop, "妈妈不在，我想玩火")

            assert not llm.calls, "危险输入不得进主 LLM"
            assert conn.kids_decision["category"] == "danger"
            spoken = "".join(conn.tts.spoken)
            assert "不可以" in spoken, "TTS 应收到阻断+安全提醒话术"
            last = conn.dialogue.dialogue[-1]
            assert last.role == "assistant" and "不可以" in last.content
        finally:
            _teardown(conn, loop, thread)

    def test_normal_input_flows_to_llm(self):
        """普通输入：三档放行，正常进主 LLM 对话。"""
        conn, llm, loop, thread = _build_llm_conn(kids=True, prime_chat=False)
        try:
            conn.websocket = FakeWebSocket()
            _run_start_to_chat(conn, loop, "给我讲个小猫的故事嘛")

            assert _wait_llm_called(llm), "放行输入应进入 chat() 调主 LLM"
            assert conn.kids_decision["category"] == "pass"
        finally:
            _teardown(conn, loop, thread)

    def test_plain_conn_danger_input_flows_to_llm(self):
        """非儿童连接：输入侧三档不生效，照常进主 LLM。"""
        conn, llm, loop, thread = _build_llm_conn(kids=False, prime_chat=False)
        try:
            conn.websocket = FakeWebSocket()
            _run_start_to_chat(conn, loop, "妈妈不在，我想玩火")

            assert _wait_llm_called(llm), "非儿童连接不受三档门影响"
            assert conn.kids_decision is None
        finally:
            _teardown(conn, loop, thread)
