"""缝 1 测试：儿童模式输出安全门 + 关怀通道（工单 #8）。

以 fake LLM/SLM/TTS 挂进 ConnectionHandler，跑真实 chat()，只断言外部
行为：TTS 队列收到的文本、对话窗口的改写、拦截事件结构、fail-open 故障
注入后的放行。provider 接口契约先例：tests/core/test_prompt_layers.py。

安全门契约（小布（源工程）accompany 移植，工单 #8）：
    主回答流结束后用 conn.slm 做六类后台分类（care/redline/danger/
    privacy/profanity/safe）；违规时丢弃已排队音频、播放含话题槽的儿童
    话术模板、改写窗口末条 assistant 消息；care 不计连拦；连拦 3 次后
    模板附加活动提议；分类故障 fail-open 放行并留痕。

运行要求：CWD 必须在 main/xiaozhi-server（与 ``make test-python`` 一致）。
"""
from __future__ import annotations

import asyncio
import copy
import queue
import threading
import uuid

from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
from tests.conftest import CONFIG

MODEL_REPLY = "这是一段不适合小朋友听的原话。"


class FakeLLM:
    """按 core/providers/llm/base.py 契约返回固定回复。"""

    def __init__(self, reply=MODEL_REPLY):
        self.reply = reply
        self.calls = []

    def response(self, session_id, dialogue):
        self.calls.append(dialogue)
        yield self.reply


class FakeMemory:
    async def query_memory(self, query):
        return ""


class FakeTTS:
    """只实现 chat()/安全门触碰到的成员。"""

    def __init__(self):
        self.tts_text_queue = queue.Queue()
        self.tts_audio_queue = queue.Queue()
        self.stored = []

    def store_tts_text(self, sentence_id, text):
        self.stored.append((sentence_id, text))

    def tts_one_sentence(self, conn, content_type, content_detail=None,
                         content_file=None, sentence_id=None):
        self.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.MIDDLE,
                content_type=content_type,
                content_detail=content_detail,
                content_file=content_file,
            )
        )


class FakeSLM:
    """后台分类小模型：response_no_stream 返回类别词（或抛错注入故障）。"""

    def __init__(self, verdict="safe", error=None):
        self.verdict = verdict
        self.error = error
        self.calls = []

    def response_no_stream(self, system_prompt, user_prompt, **kwargs):
        self.calls.append((system_prompt, user_prompt))
        if self.error is not None:
            raise self.error
        return self.verdict


def _make_conn(kids=None):
    """构造挂了 fake 组件的 ConnectionHandler（不跑对话）。"""
    from core.connection import ConnectionHandler

    config = copy.deepcopy(CONFIG)
    if kids is not None:
        config["kids"] = kids
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
    conn.device_id = f"kids-gate-test-{uuid.uuid4().hex}"
    conn._init_prompt_enhancement()
    conn._loop_thread = loop_thread
    return conn


def _teardown(conn):
    conn._loop_thread and conn.loop.call_soon_threadsafe(conn.loop.stop)
    conn._loop_thread.join(timeout=5)
    conn.loop.close()


def _drain_tts(conn):
    items = []
    while True:
        try:
            items.append(conn.tts.tts_text_queue.get_nowait())
        except queue.Empty:
            return items


def _spoken_text(conn):
    """孩子实际听到（被送进 TTS 通道）的完整文本。"""
    items = _drain_tts(conn)
    return "".join(
        i.content_detail or "" for i in items if i.content_type == ContentType.TEXT
    )


def _run_chat(conn, slm, text="给我讲个鬼故事"):
    conn.slm = slm
    conn.chat(text)


def test_redline_violation_replaces_audio_and_rewrites_window():
    """违规轮：TTS 队列收到模板而非模型原文，窗口末条被改写，拦截事件落结构。"""
    from core.kids_safety import SAFETY_INSTR

    conn = _make_conn(kids={"enabled": True})
    try:
        slm = FakeSLM(verdict="redline")
        _run_chat(conn, slm)

        spoken = _spoken_text(conn)
        # 模板共性关键词（xb 注释：每类保证一个共性关键词供辨认），
        # 而非模型原文
        assert "不知道" in spoken, f"应播放 redline 兜底模板，实际: {spoken}"
        assert MODEL_REPLY not in spoken, "模型原文不应再被送到 TTS"
        assert "{topic}" not in spoken, "话题槽位必须被填充"

        # 窗口改写：末条 assistant = 孩子实际听到的话术
        last = conn.dialogue.dialogue[-1]
        assert last.role == "assistant"
        assert last.content == spoken, "窗口末条应被改写为孩子实际听到的话术"

        # 拦截事件结构（落库归 #9，本票只产出统一 dict）
        events = conn.kids_interceptions
        assert len(events) == 1
        ev = events[0]
        assert set(ev) >= {"t", "when", "cat", "user", "reply", "actual"}
        assert ev["cat"] == "redline"
        assert ev["user"] == "给我讲个鬼故事"
        assert ev["reply"] == MODEL_REPLY
        assert ev["actual"] == spoken
        assert isinstance(ev["t"], float) and ev["t"] > 0
    finally:
        _teardown(conn)


def test_bypass_completely_when_kids_disabled():
    """非儿童模式（开关关）完全旁路：SLM 不被调用，模型原文照常播出。"""
    conn = _make_conn()  # 不设 kids 块
    try:
        slm = FakeSLM(verdict="redline")
        _run_chat(conn, slm)
        assert slm.calls == [], "非儿童模式不应触发分类"
        assert _spoken_text(conn) == MODEL_REPLY
        assert conn.kids_interceptions == []
        assert conn.dialogue.dialogue[-1].content == MODEL_REPLY
    finally:
        _teardown(conn)


def test_classification_prompt_contract():
    """SLM 收到逐字移植的分类指令与【孩子说的】/【小智回答的】节结构。"""
    from core.kids_safety import SAFETY_INSTR

    conn = _make_conn(kids={"enabled": True})
    try:
        slm = FakeSLM(verdict="safe")
        _run_chat(conn, slm)
        assert slm.calls, "应收到一次分类请求"
        system_prompt, user_prompt = slm.calls[0]
        assert system_prompt == SAFETY_INSTR
        assert user_prompt == (
            "【孩子说的】\n给我讲个鬼故事\n【小智回答的】\n" + MODEL_REPLY
        )
    finally:
        _teardown(conn)


def test_safe_verdict_passes_through():
    """safe：模型原文照常播出，窗口不改写，无拦截事件。"""
    conn = _make_conn(kids={"enabled": True})
    try:
        slm = FakeSLM(verdict="safe")
        _run_chat(conn, slm)
        assert _spoken_text(conn) == MODEL_REPLY
        assert conn.dialogue.dialogue[-1].content == MODEL_REPLY
        assert conn.kids_interceptions == []
        assert conn.kids_safety_failures == []
    finally:
        _teardown(conn)


def test_care_channel_gentle_template_without_secrecy():
    """care：温柔回应+引导告诉家长+永不承诺保密；不计连拦（不触发活动提议）。"""
    conn = _make_conn(kids={"enabled": True})
    try:
        _run_chat(conn, FakeSLM(verdict="care"))
        spoken = _spoken_text(conn)
        assert "保密" in spoken and "爸爸妈妈" in spoken, f"care 模板应含保密拒绝: {spoken}"
        assert conn.dialogue.dialogue[-1].content == spoken
        assert [e["cat"] for e in conn.kids_interceptions] == ["care"]

        # care 不计连拦：随后两次违规不应触发活动提议（若 care 计数则第 2 次即满 3）
        _run_chat(conn, FakeSLM(verdict="redline"))
        spoken2 = _spoken_text(conn)
        assert "不知道" in spoken2
        assert "要不要" not in spoken2, "care 不应计入连拦"
        _run_chat(conn, FakeSLM(verdict="redline"))
        spoken3 = _spoken_text(conn)
        assert "要不要" not in spoken3, "两次违规（care 不计数）不应有活动提议"
        assert [e["cat"] for e in conn.kids_interceptions] == ["care", "redline", "redline"]
    finally:
        _teardown(conn)


def test_three_consecutive_blocks_append_activity_then_reset():
    """连拦 3 次后模板附加活动提议，随后计数清零。"""
    conn = _make_conn(kids={"enabled": True})
    try:
        for _ in range(2):
            _run_chat(conn, FakeSLM(verdict="danger"))
            assert "要不要" not in _spoken_text(conn), "前两次拦截不应有活动提议"

        _run_chat(conn, FakeSLM(verdict="danger"))
        spoken3 = _spoken_text(conn)
        assert "不可以" in spoken3, "danger 模板共性关键词"
        assert "要不要" in spoken3, "第 3 次连拦应附加活动提议"
        assert "{topic}" not in spoken3
        assert conn.dialogue.dialogue[-1].content == spoken3

        # 计数已清零：下一轮拦截重新数，无活动提议
        _run_chat(conn, FakeSLM(verdict="danger"))
        assert "要不要" not in _spoken_text(conn), "活动提议后计数应清零"
    finally:
        _teardown(conn)


def test_fail_open_on_slm_error_keeps_dialogue_and_records():
    """分类 API 故障：对话不中断、原文放行、窗口不改写、故障留痕。"""
    conn = _make_conn(kids={"enabled": True})
    try:
        _run_chat(conn, FakeSLM(error=RuntimeError("dashscope 503")))
        assert _spoken_text(conn) == MODEL_REPLY, "fail-open 不应丢弃已排队音频"
        assert conn.dialogue.dialogue[-1].content == MODEL_REPLY
        assert conn.kids_interceptions == []
        assert len(conn.kids_safety_failures) == 1, "故障应留痕"
        assert "dashscope 503" in conn.kids_safety_failures[0]["error"]

        # 对话不中断：下一轮照常工作
        _run_chat(conn, FakeSLM(verdict="safe"))
        assert _spoken_text(conn) == MODEL_REPLY
        assert len(conn.dialogue.dialogue) == 5  # system + 两轮 user+assistant
    finally:
        _teardown(conn)


def test_fail_open_on_unrecognizable_verdict():
    """分类输出不可识别：fail-open 放行并留痕。"""
    conn = _make_conn(kids={"enabled": True})
    try:
        _run_chat(conn, FakeSLM(verdict="我认为这段话没有问题"))
        assert _spoken_text(conn) == MODEL_REPLY
        assert conn.kids_interceptions == []
        assert len(conn.kids_safety_failures) == 1
    finally:
        _teardown(conn)


def test_topic_slot_prefers_profile_hobby():
    """槽位来源含档案「爱好」：配置扁平 hobbies 键（与 kids_profile/下发一致）后模板话题用它。"""
    conn = _make_conn(kids={"enabled": True, "hobbies": "恐龙"})
    try:
        _run_chat(conn, FakeSLM(verdict="redline"))
        spoken = _spoken_text(conn)
        assert "恐龙" in spoken, f"槽位应取档案爱好: {spoken}"
    finally:
        _teardown(conn)


def test_pick_topic_tier_order():
    """槽位取材优先级：记忆最新条目（剥「喜欢」前缀）→ 档案爱好 → 静态兜底。"""
    from core.kids_safety import FALLBACK_TOPICS, pick_topic

    assert pick_topic(["喜欢小汽车", "喜欢恐龙"]) == "恐龙"
    # 记忆优先于爱好，且只剥前缀不做其它改写
    assert pick_topic(["已经不喜欢的旧条目"], "画画") == "已经不喜欢的旧条目"
    assert pick_topic(["喜欢小汽车"], "画画") == "小汽车"
    assert pick_topic([], "画画") == "画画"
    assert pick_topic(None, None) in FALLBACK_TOPICS
    assert pick_topic(["", "喜欢"], None) in FALLBACK_TOPICS  # 空条目跳过
