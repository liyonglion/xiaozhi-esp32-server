"""儿童陪伴模式输出安全门 + 关怀通道（spec #1 / 工单 #8）。

移植自小布 accompany 的输出侧安全双保险（core/src/xb_core.c），分类
prompt 与话术模板逐字保留（prompt 契约：节标题与模板措辞维持模型行为）。

- 主回答流结束后用 SLM（``conn.slm``，独立于主对话模型）做六类后台分类，
  与 TTS 合成并行：TTS 消费线程独立泵音频，分类阻塞不等人。
- 违规（含 care 关怀通道）时丢弃在播/在途音频，播放含话题槽的兜底话术
  模板，并把窗口末条 assistant 消息改写为孩子实际听到的话术——下轮 LLM
  不再「记得」被拦原文而延续坏方向（append-only 窗口的唯一例外）。
- care 由孩子的话触发，是独立关怀通道不是拦截：不计连拦、不附活动提议、
  永不承诺保密（话术模板逐字保证）。
- 非 care 连拦 3 次后，模板追加活动提议（讲故事/玩游戏/儿歌）并重新计数。
- 分类请求异常/超时/输出不可识别一律 fail-open 放行并留痕，对话不因
  审核通道故障中断，连拦计数清零。
- 拦截事件为统一 dict 结构，挂连接级内存列表 ``conn.kids_interceptions``；
  回合结束由 :func:`flush_interceptions` 排空并经 manager-api 通道整批
  上报，环形 500 条与 care/redline 豁免挤出在持久层（工单 #9）。

话术模板来源：xb_core.c TPL_*（逐字）；槽位取材优先级：记忆最新条目
（剥「喜欢」前缀）→ 档案「爱好」→ 静态兜底词随机。
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime

from config.manage_api_client import report_interceptions
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO

# 红线/危险话术与兜底话题与输入侧三档（core.kids）同源：小布 TPL_* 逐字，
# 单一样本源，输入侧（#5）与输出侧（#8）共用
from core.kids import (
    DANGER_TEMPLATES as TPL_DANGER,
    REDLINE_TEMPLATES as TPL_REDLINE,
    FALLBACK_TOPICS,
)

TAG = __name__

# 分类指令（静态文本：每趟校验前缀稳定，缓存友好）。只审回答本身；care 由
# 孩子的话触发（自残/受侵害暗示），是独立通道不是拦截
SAFETY_INSTR = (
    "你是儿童对话安全审核员。下面给你一段孩子的话和小布的回答，"
    "只审核小布的回答，输出一个类别词，除类别词外什么都不要输出：\n"
    "care——孩子说不想活了、要伤害自己，或说被人打、被人欺负、被侵害\n"
    "redline——小布对孩子讲了血腥暴力、色情、恐怖吓人、赌博吸毒等硬红线内容\n"
    "danger——小布同意、示范或教孩子做危险的事（玩火、爬窗、触电、吃异物、"
    "跟陌生人走、离家出走等）\n"
    "privacy——小布主动询问孩子的家庭住址、密码、学校名字、家长手机号\n"
    "profanity——孩子说了脏话，小布跟着说、重复脏话或没有纠正\n"
    "safe——以上都不是"
)

# 违规类先扫，safe 兜底；识别不了由调用侧 fail-open
SAFETY_CATS = ("care", "redline", "danger", "privacy", "profanity", "safe")

# 兜底模板（按类别分组；同类内随机轮换；{topic} 为槽位）。每类保证一个共性
# 关键词，家长与测试凭它辨认类别（care 不带槽位：关怀轮不转移话题）
TPL_CARE = (
    "听到你这么说，我心里紧紧的，好心疼你。快去告诉爸爸妈妈好不好？"
    "我不能帮你保密，因为我好想你平平安安。",
    "这件事太大啦，一定要让爸爸妈妈知道。我答应不了保密，"
    "但我会一直陪着你，去拉拉妈妈的手好不好？",
)
TPL_PRIVACY = (
    "这个呀，要问过爸爸妈妈才能说哦。我们还是聊聊{topic}吧！",
    "这个要爸爸妈妈才能回答哦。来，说说{topic}？",
)
TPL_PROFANITY = (
    "这样说不好听哦，我们嘴巴甜甜的。来，聊聊{topic}？",
    "这个词不好听哦，我们不学它。说说{topic}好不好？",
)
# 连拦 3 轮追加的活动提议（槽位同源：记忆/档案爱好）
TPL_ACTIVITY = (
    "要不要我讲一个{topic}的故事呀？",
    "要不要我们一起玩{topic}的游戏？",
    "要不要听听{topic}的儿歌呀？",
)


# 类别 → 兜底模板组（单张表，避免类别判断散落多处）
SAFETY_TPLS = {
    "care": TPL_CARE,
    "redline": TPL_REDLINE,
    "danger": TPL_DANGER,
    "privacy": TPL_PRIVACY,
    "profanity": TPL_PROFANITY,
}

# 内存事件上限（环形语义归 #9 的持久层；这里只防长连接无界增长）
_EVENTS_MAX = 500


def parse_safety_class(text):
    """模型输出里找类别词（违规类先扫，safe 兜底）；识别不了返回 None。"""
    if not text:
        return None
    for cat in SAFETY_CATS:
        if cat in text:
            return cat
    return None


def pick_topic(memory_entries=None, profile_hobby=None):
    """槽位取材：记忆最新条目（剥「喜欢」前缀）→ 档案「爱好」→ 静态兜底词。

    只取词不改写（模板措辞已适配名词性槽位）。
    """
    for entry in reversed(list(memory_entries or [])):
        text = (entry or "").strip()
        if text.startswith("喜欢"):
            text = text[len("喜欢"):]
        if text:
            return text
    hobby = (profile_hobby or "").strip()
    if hobby:
        return hobby
    return random.choice(FALLBACK_TOPICS)


def render_tpl(tpl, topic):
    """模板渲染：{topic} → 槽位词。"""
    return tpl.replace("{topic}", topic)


def _now_str():
    return datetime.now().strftime("%m-%d %H:%M")


def _append_capped(events, event):
    events.append(event)
    if len(events) > _EVENTS_MAX:
        del events[: len(events) - _EVENTS_MAX]


def _record_failure(conn, reason):
    """fail-open 留痕：日志 + 连接级故障列表（对话照常放行）。"""
    conn.logger.bind(tag=TAG).warning(f"安全校验失败，本轮放行（fail-open）: {reason}")
    _append_capped(
        conn.kids_safety_failures, {"t": time.time(), "when": _now_str(), "error": reason}
    )


def _pick_topic_for_conn(conn):
    """连接级槽位取材：记忆条目（#7 的儿童记忆 provider 落地后接入）→ 档案爱好。"""
    kids = conn.config.get("kids") or {}
    # ponytail: 记忆来源暂缺——工单 #7 的儿童记忆 provider 未落地，
    # 落地后在此传入其最新条目列表（pick_topic 已支持）
    memory_entries = None
    profile_hobby = (kids.get("profile") or {}).get("爱好")
    return pick_topic(memory_entries, profile_hobby)


def _discard_pending_audio(conn):
    """弃在播/在途音频（照抄打断先例 abortHandle）：停消费、清队列、通知设备停。"""
    conn.client_abort = True
    conn.clear_queues()
    ws = getattr(conn, "websocket", None)
    if ws is not None:
        asyncio.run_coroutine_threadsafe(
            ws.send(
                json.dumps({"type": "tts", "state": "stop", "session_id": conn.session_id})
            ),
            conn.loop,
        )
    conn.clearSpeakStatus()
    # 恢复打断标记，让兜底模板照常走 TTS 通道
    conn.client_abort = False


def _speak_template(conn, tpl):
    """兜底话术经正常 TTS 通道分句播出（复用 speak_txt 三连，不写对话窗口）。"""
    sid = conn.sentence_id
    conn.tts.store_tts_text(sid, tpl)
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=sid,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
    )
    conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=tpl)
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=sid,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        )
    )


def _rewrite_last_assistant(conn, assistant_msg, tpl):
    """窗口末条内容替换：窗口里的 assistant=孩子实际听到的兜底话术。

    仅当末条仍是本轮assistant 消息对象时替换（防与新轮对话交错错改）。
    """
    msgs = conn.dialogue.dialogue
    if msgs and msgs[-1] is assistant_msg:
        assistant_msg.content = tpl
    else:
        conn.logger.bind(tag=TAG).warning("窗口末条已变化，跳过改写（保留原话）")


def _safety_block(conn, cat, user_text, reply_text, assistant_msg):
    """拦截动作：弃音频换模板 + 改写窗口 + 记拦截事件。"""
    topic = _pick_topic_for_conn(conn)
    tpl = render_tpl(random.choice(SAFETY_TPLS.get(cat, TPL_PROFANITY)), topic)
    if cat == "care":
        conn.kids_block_streak = 0  # 关怀不是拦，也不宜跟活动提议
    else:
        conn.kids_block_streak += 1
        if conn.kids_block_streak >= 3:
            tpl += render_tpl(random.choice(TPL_ACTIVITY), topic)
            conn.kids_block_streak = 0
    _discard_pending_audio(conn)
    _speak_template(conn, tpl)
    _rewrite_last_assistant(conn, assistant_msg, tpl)
    conn.logger.bind(tag=TAG).error(f"安全拦截：类别 {cat}，已换兜底话术")
    _append_capped(
        conn.kids_interceptions,
        {
            "t": time.time(),
            "when": _now_str(),
            "cat": cat,
            "user": user_text,
            "reply": reply_text,
            "actual": tpl,
        },
    )


def flush_interceptions(conn):
    """回合结束：排空拦截事件并经 manager-api 通道整批上报（工单 #9）。

    文件模式（未配 manager-api）跳过上报、内存留痕保留；环形 500 条与
    care/redline 豁免挤出语义在 manager-api 持久层（入库后裁剪），Python
    内存列表只做传输。上报失败仅记日志（fail-open，不阻塞对话）。
    """
    if not conn.read_config_from_api or conn.need_bind:
        return
    events = conn.kids_interceptions
    if not events:
        return
    conn.kids_interceptions = []
    if conn.executor is None:
        return

    def _upload():
        try:
            asyncio.run(report_interceptions(conn.device_id, events))
        except Exception as e:  # noqa: BLE001 上报故障不连坐对话（fail-open）
            conn.logger.bind(tag=TAG).error(f"拦截日志上报失败: {e}")

    try:
        conn.executor.submit(_upload)
    except Exception as e:  # noqa: BLE001 线程池关闭期提交失败：仅留日志
        conn.logger.bind(tag=TAG).error(f"拦截日志上报任务提交失败: {e}")


def run_safety_gate(conn, user_text):
    """安全门主体：SLM 分类校验（与 TTS 合成并行），失败一律 fail-open。

    在 chat() 主回答流结束、LAST 入队后调用；非儿童模式（kids.enabled 关）
    完全旁路。
    """
    if not (conn.config.get("kids") or {}).get("enabled"):
        return
    assistant_msg = next(
        (m for m in reversed(conn.dialogue.dialogue) if m.role == "assistant"), None
    )
    if assistant_msg is None or not (assistant_msg.content or "").strip():
        return  # 本轮无模型输出可审（如错误兜底路径）
    reply_text = assistant_msg.content

    if conn.slm is None:
        conn.kids_block_streak = 0
        _record_failure(conn, "SLM 槽位未配置，审核通道不可用")
        return
    prompt = f"【孩子说的】\n{user_text or ''}\n【小布回答的】\n{reply_text}"
    try:
        verdict = conn.slm.response_no_stream(SAFETY_INSTR, prompt)
    except Exception as e:  # noqa: BLE001 fail-open：审核通道故障不连坐对话
        conn.kids_block_streak = 0
        _record_failure(conn, f"分类请求异常: {e}")
        return
    cat = parse_safety_class(verdict)
    if cat is None:
        conn.kids_block_streak = 0
        _record_failure(conn, f"分类输出不可识别: {verdict!r}")
        return
    if cat == "safe":
        conn.kids_block_streak = 0
        return
    _safety_block(conn, cat, user_text, reply_text, assistant_msg)
