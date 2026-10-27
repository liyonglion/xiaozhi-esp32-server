"""口算练习插件（地图 #20 决议实现，切片①）。

三个工具：
- start_practice(difficulty, mode)：开新轮 / 继续断点 / 重开
- submit_answer(answer)：确定性判题（归一化→精确比较），答错两次给讲解素材+巩固题
- end_practice：主动退出收尾

分工（#24/#26 决议）：数字事实全部由工具计算（出题器/讲解素材），LLM 只负责
组织孩子听得懂的话；题面经 send_display_message 上屏，答题回显顶掉后补发恢复。

判定循环（#23 决议）：每题 2 次作答机会；30s 无作答轻推一次，再 30s 跳过并讲解。
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
from core.providers.tools.device_mcp import call_mcp_tool
from mcp_services.math_practice import explanations, generator
from mcp_services.math_practice.session import new_session, store, view_text
from plugins_func.register import Action, ActionResponse, ToolType, register_function

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__

_timers: dict[str, asyncio.Task] = {}
_report_tasks: set[asyncio.Task] = set()  # 持引用防 GC；fire-and-forget 上报/推送
_last_streak_end: dict[str, int] = {}  # 设备最近一次收尾上报的 streak（进程内续接兜底，#29）
_push_locks: dict[str, asyncio.Lock] = {}  # per-device FIFO：推送按判决顺序落屏

_PRESET_KEYS = {
    "学前": "preschool", "幼儿园": "preschool",
    "一年级上": "g1a", "一上": "g1a", "一年级上册": "g1a",
    "一年级下": "g1b", "一下": "g1b", "一年级下册": "g1b",
    "二年级上": "g2a", "二上": "g2a", "二年级上册": "g2a",
    "二年级下": "g2b", "二下": "g2b", "二年级下册": "g2b",
    "一年级": "g1b", "二年级": "g2b",
}


def _plugin_cfg(conn: "ConnectionHandler") -> dict:
    return conn.config.get("plugins", {}).get("math_practice", {})


def _resolve_preset(difficulty: str) -> str:
    if not difficulty:
        return generator.FALLBACK_PRESET
    d = difficulty.strip()
    if d in generator.PRESETS:
        return d
    for key, preset in _PRESET_KEYS.items():
        if key in d:
            return preset
    return generator.FALLBACK_PRESET


async def _fetch_device_config(conn: "ConnectionHandler") -> dict | None:
    """拉 admin 家长页配置的设备级口算配置（切片②）。独立函数便于测试 stub。"""
    from config import manage_api_client

    return await manage_api_client.get_math_practice_config(conn.device_id)


MIN_COUNT, MAX_COUNT = 5, 20  # 每轮题量档位（#23 决议：默认 10，可配 5~20，三层统一）


async def _device_overrides(conn: "ConnectionHandler", difficulty: str) -> tuple[str, list[str], int, int]:
    """解析生效配置：远端设备配置 > difficulty 入参 > config.yaml 默认（#24 决议）。

    远端字段不可信（可能过期/手改库），逐项校验后采用，非法值忽略。
    返回 (preset, type_ids, count, streak_seed)；seed 取 record 口径与进程内口径的较大值
    （#29：record 落库有延迟，进程内值兜住「连玩两轮」的续接）。
    """
    preset = _resolve_preset(difficulty)
    type_ids = list(generator.PRESETS[preset])
    count = max(MIN_COUNT, min(MAX_COUNT, int(_plugin_cfg(conn).get("count", 10))))
    seed = _last_streak_end.get(conn.device_id, 0)
    if conn.config.get("read_config_from_api"):
        try:
            remote = await _fetch_device_config(conn)
        except Exception:
            remote = None  # 配置页不可用不拦练习，回落默认
        if remote:
            if remote.get("preset") in generator.PRESETS:
                preset = remote["preset"]
                type_ids = list(generator.PRESETS[preset])
            ids = [t for t in (remote.get("typeIds") or []) if t in generator.TYPES]
            if ids:
                type_ids = ids
            try:
                count = max(MIN_COUNT, min(MAX_COUNT, int(remote.get("questionCount") or count)))
            except (TypeError, ValueError):
                pass
            try:
                seed = max(seed, int(remote.get("streakEnd") or 0))
            except (TypeError, ValueError):
                pass
    return preset, type_ids, count, seed


async def _report_result(conn: "ConnectionHandler", s: dict) -> None:
    """收尾上报练习记录（#24：一次会话一行）。独立函数便于测试 stub。"""
    from config import manage_api_client

    await manage_api_client.report_math_practice(
        conn.device_id,
        s.get("preset", ""),
        s["total"],
        s["score"],
        int(time.time() - s["started_at"]),
        s["streak"],
        s["streak_peak"],
    )


async def _report_and_push(conn: "ConnectionHandler", s: dict) -> None:
    """收尾：先上报再推纯聚合，整体持 per-device 锁——慢上报期间新一轮的判决推送
    只能排队其后，收尾推送不会被后判决顶回旧值（#29 FIFO 序保证）。"""
    try:
        async with _device_push_lock(conn.device_id):
            await _report_result(conn, s)  # api_guard 兜底不抛错；失败也继续推（少算好过不推）
            await _push_locked(conn, None)
    except Exception as e:  # 收尾旁路，绝不影响播报主流程
        try:
            conn.logger.bind(tag=TAG).warning(f"学习进度收尾推送中断: {e}")
        except Exception:
            pass


def _report_in_background(conn: "ConnectionHandler", s: dict) -> None:
    """fire-and-forget 上报：记录接口带重试（最长分钟级），不能拖住收尾播报。

    收尾推送排在上报之后（record 落库后聚合才含本会话，#29）；
    同步记进程内 streak_end，供「连玩两轮」免等落库即续接。
    """
    _remember_streak_end(conn.device_id, s["streak"])
    task = asyncio.create_task(_report_and_push(conn, s))
    _report_tasks.add(task)
    task.add_done_callback(_report_tasks.discard)


def _push_in_background(conn: "ConnectionHandler", s: dict) -> None:
    """判决推进后的进度推送（#29：固件无状态，全量 8 字段）。"""
    task = asyncio.create_task(_push_progress(conn, s))
    _report_tasks.add(task)
    task.add_done_callback(_report_tasks.discard)


def _remember_streak_end(device_id: str, streak: int) -> None:
    if len(_last_streak_end) > 1024:  # ponytail: 粗上限防连接churn膨胀；真到千设备量级再换 LRU
        _last_streak_end.clear()
    _last_streak_end[device_id] = streak


def _device_push_lock(device_id: str) -> asyncio.Lock:
    if len(_push_locks) > 1024:
        # ponytail: 粗上限防连接churn膨胀。只清未被持有的锁——在途任务持有的锁被清后，
        # 同设备 setdefault 出的新锁会绕过 FIFO 互斥（评审发现）。真到千设备量级再换 LRU。
        held = {k: v for k, v in _push_locks.items() if v.locked()}
        _push_locks.clear()
        _push_locks.update(held)
    return _push_locks.setdefault(device_id, asyncio.Lock())


def _overlay_live(agg: dict, s: dict) -> dict:
    """会话进行中的推送：历史聚合 + 本会话实时值（record 仅收尾落库，中间态由会话补）。

    ponytail: 假定本会话落在「今日/本周」——跨零点续练会记入今日，落库后由
    下一次聚合自然纠正；固件侧另有 NVS 跨天清零兜底。
    """
    week_correct = int(agg.get("weekCorrect", 0)) + s["score"]
    week_total = int(agg.get("weekTotal", 0)) + s["answered"]
    sessions = list(agg.get("recentSessions") or [])
    if s["answered"] > 0:
        sessions = [{
            "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(s["started_at"])),
            "correct": s["score"],
            "total": s["answered"],
            "streakPeak": s["streak_peak"],
        }, *sessions]
    # 整数半进位（floor(x+0.5)），与 Java Math.round 口径一致，防 .5 处来回跳 1
    accuracy = (week_correct * 200 + week_total) // (week_total * 2) if week_total else 0
    return {
        "todayCorrect": int(agg.get("todayCorrect", 0)) + s["score"],
        "todayTotal": int(agg.get("todayTotal", 0)) + s["answered"],
        "todayMaxStreak": max(int(agg.get("todayMaxStreak", 0)), s["streak_peak"]),
        "currentStreak": s["streak"],
        "bestStreak": max(int(agg.get("bestStreak", 0)), s["streak_peak"]),
        "weekAccuracy": accuracy,
        "recentSessions": sessions[:5],
    }


async def _push_locked(conn: "ConnectionHandler", s: dict | None) -> None:
    """锁内推送：s=None 推纯聚合（收尾后），s 非 None 叠加本会话实时值。

    未配 token / 设备未注册 update_progress / 未就绪：静默跳过（旧固件、未部署）。
    """
    from config import manage_api_client

    token = _plugin_cfg(conn).get("progress_token", "")
    mcp = getattr(conn, "mcp_client", None)
    if not token or mcp is None or not mcp.has_tool("update_progress"):
        return
    if not await mcp.is_ready():
        return
    try:
        agg = await manage_api_client.get_math_practice_progress(conn.device_id, token)
    except Exception as e:
        # 持续性失败（如 token 配错 401）打 warning 可观测；瞬时失败同样跳过，下一次判决补推
        conn.logger.bind(tag=TAG).warning(f"学习进度聚合拉取失败: {e}")
        return
    if agg is None:
        return
    payload = _overlay_live(agg, s) if s is not None else agg
    await call_mcp_tool(conn, mcp, "update_progress", payload)


async def _push_progress(conn: "ConnectionHandler", s: dict | None) -> None:
    """判决后的推送入口：per-device FIFO 锁内执行（按判决顺序落屏，#29）。"""
    try:
        async with _device_push_lock(conn.device_id):
            await _push_locked(conn, s)
    except Exception as e:  # 推送是旁路，绝不影响答题主流程
        try:
            conn.logger.bind(tag=TAG).warning(f"学习进度推送中断: {e}")
        except Exception:
            pass


def _advance(s: dict, scored: bool) -> dict:
    """推进到下一题（巩固题不计题量、不循环）；主题全部作答完毕时 answered == total。

    streak（#29）：主题答对 +1、判错/超时清零；巩固题不参与（学习环节非考核）。
    """
    role = s["questions"][s["idx"]]["role"]
    is_main = role == "main"
    streak = s["streak"]
    if is_main:
        streak = s["streak"] + 1 if scored else 0
    return {
        **s,
        "idx": s["idx"] + 1,
        "attempts": 0,
        "score": s["score"] + (1 if scored and is_main else 0),
        "answered": s["answered"] + (1 if is_main else 0),
        "main_no": s["main_no"] + (1 if is_main else 0),
        "streak": streak,
        "streak_peak": max(s["streak_peak"], streak),
    }


def _wrap_up_text(s: dict) -> str:
    return f"答对{s['score']}题，共{s['total']}题"


async def _say(conn: "ConnectionHandler", text: str) -> None:
    """直接排队一句 TTS（超时提醒等无 LLM 参与的播报）。"""
    conn.tts.store_tts_text(conn.sentence_id, text)
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail=text,
        )
    )


async def _show_question(conn: "ConnectionHandler", s: dict) -> None:
    """题面上屏 + 无声字幕恢复（答题回显会顶掉单槽屏的题面，#22 调研结论）。

    懒导入：sendAudioHandle 带 opuslib 等重依赖，也便于测试 stub。
    """
    from core.handle.sendAudioHandle import send_display_message, send_tts_message

    view = view_text(s)
    await send_display_message(conn, view)
    await send_tts_message(conn, "sentence_start", view)


async def _respond_next(conn: "ConnectionHandler", s: dict, scored: bool, lead: str) -> ActionResponse:
    """推进到下一题或收尾（收尾用推进后的计分），返回给 LLM 的引导。"""
    s2 = _advance(s, scored)
    if s2["answered"] >= s2["total"]:
        store.delete(conn.device_id)
        _cancel_timer(conn.device_id)
        _report_in_background(conn, s2)
        return ActionResponse(
            action=Action.REQLLM,
            result=(
                f"练习完成！孩子{_wrap_up_text(s2)}。"
                "请按孩子的表现收尾：表现好就大力表扬，错得多也要找到亮点鼓励。"
                "最后问孩子要不要再来一轮；孩子同意就调用 start_practice 重新开始。"
            ),
        )
    saved = store.save({**s2, "timeout_skips": 0})  # 有作答即重置连续超时计数
    _bump_timer(conn, saved)
    _push_in_background(conn, saved)
    await _show_question(conn, saved)
    return ActionResponse(
        action=Action.REQLLM,
        result=f"{lead}然后读下一题：{view_text(saved)}。孩子回答后继续调用 submit_answer。",
    )


def _start_timer(conn: "ConnectionHandler", s: dict) -> None:
    nudge = float(_plugin_cfg(conn).get("nudge_seconds", 30))
    if nudge <= 0:
        return
    device_id = conn.device_id
    token = s["last_active"]
    _timers[device_id] = asyncio.create_task(_nudge_loop(conn, device_id, token, nudge))


def _bump_timer(conn: "ConnectionHandler", s: dict) -> None:
    old = _timers.pop(conn.device_id, None)
    if old:
        old.cancel()
    _start_timer(conn, s)


def _cancel_timer(device_id: str) -> None:
    task = _timers.pop(device_id, None)
    if task:
        task.cancel()


async def _nudge_loop(conn: "ConnectionHandler", device_id: str, token: float, nudge: int) -> None:
    """两级超时（#23）：30s 轻推一次，再 30s 跳过并讲解，然后读下一题。"""
    try:
        await asyncio.sleep(nudge)
        s = store.get(device_id)
        if s is None or s["last_active"] != token:
            return
        await _say(conn, "别急，再想一想，想好了告诉我。")
        await asyncio.sleep(nudge)
        s = store.get(device_id)
        if s is None or s["last_active"] != token:
            return
        qq = s["questions"][s["idx"]]
        material = explanations.build_material(qq)
        await _say(conn, f"没关系，这道题先跳过。正确答案是{material['answer']}。{material['steps']}")
        s2 = _advance(s, scored=False)
        if s2["answered"] >= s2["total"]:
            store.delete(device_id)
            _report_in_background(conn, s2)
            await _say(conn, f"练习结束，{_wrap_up_text(s2)}，你很棒！")
            return
        skips = s.get("timeout_skips", 0) + 1
        saved = store.save({**s2, "timeout_skips": skips})
        if skips >= 2:
            # 连续无作答视为被动中断（跑题/离开）：停超时链保留会话供 resume，
            # 避免自动跳完全轮并上报失真记录（session.py 生命周期决议）
            _timers.pop(device_id, None)  # 本 task 即链尾，清掉自身引用
            _push_in_background(conn, saved)  # 停链也推一次（#29：屏停在本场实时值）
            await _say(conn, "我们先休息一下，想继续练口算随时叫我哦。")
            return
        _push_in_background(conn, saved)  # 超时跳过=不会，streak 已清零（#29）
        await _say(conn, f"下一题：{view_text(saved)}")
        await _show_question(conn, saved)
        _start_timer(conn, saved)
    except asyncio.CancelledError:
        pass
    except Exception as e:  # 连接可能已断，超时链静默终止
        try:
            conn.logger.bind(tag=TAG).warning(f"口算练习超时提醒中断: {e}")
        except Exception:
            pass


start_practice_desc = {
    "type": "function",
    "function": {
        "name": "start_practice",
        "description": (
            "当孩子想练习口算/数学时调用，开始一轮口算练习。"
            "difficulty：年级或难度，可选值：学前、一年级上、一年级下、二年级上、二年级下；"
            "设备未配置时先问孩子上几年级再传入，孩子说不清就留空。"
            "mode：工具提示已有进行中的练习时才需要——孩子选继续传 resume，选重新开始传 restart。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "difficulty": {"type": "string", "description": "年级或难度描述，如：一年级下"},
                "mode": {"type": "string", "description": "resume=继续上次，restart=重新开始，默认空"},
            },
            "required": [],
        },
    },
}


@register_function("start_practice", start_practice_desc, ToolType.SYSTEM_CTL)
async def start_practice(conn: "ConnectionHandler", difficulty: str = "", mode: str = ""):
    device_id = conn.device_id
    existing = store.get(device_id)
    if existing is not None and mode == "":
        return ActionResponse(
            action=Action.REQLLM,
            result=(
                f"该设备已有一轮进行中的练习（第{existing['main_no']}/{existing['total']}题）。"
                "请询问孩子：继续上次的，还是重新开始？孩子选继续就调用 start_practice(mode='resume')，"
                "选重新开始就调用 start_practice(mode='restart')。"
            ),
        )
    if existing is not None and mode == "resume":
        _bump_timer(conn, existing)
        await _show_question(conn, existing)
        return ActionResponse(
            action=Action.REQLLM,
            result=(
                f"继续上次的练习，当前第{existing['main_no']}/{existing['total']}题。"
                f"请说一句「我们继续练口算啦」，然后读题：{view_text(existing)}。"
                "孩子回答后调用 submit_answer(answer=孩子的原话)。"
            ),
        )
    preset, type_ids, total, streak_seed = await _device_overrides(conn, difficulty)
    questions = generator.generate_practice(type_ids, total, random.Random())
    total = len(questions)  # 小题库（如仅 A1 去重后 12 题）可能不足 count，对齐防越界
    s = store.save(new_session(device_id, questions, total, preset, streak=streak_seed))
    _bump_timer(conn, s)
    await _show_question(conn, s)
    return ActionResponse(
        action=Action.REQLLM,
        result=(
            f"口算练习开始（{generator.PRESET_NAMES[preset]}），共{total}题。"
            "请热情地开个场，然后把第一题清楚地读给孩子听："
            f"{view_text(s)}。等孩子口头回答后，调用 submit_answer(answer=孩子说的原话)。不要替孩子答题。"
        ),
    )


submit_answer_desc = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": (
            "口算练习中，孩子每口头回答一次就调用一次，传入孩子说的话原文。"
            "答案可以是数字（如 12 或 十二）或比大小符号（大于/小于/等于）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "孩子口头回答的原话，如：三十五 / 17 / 大于号"},
            },
            "required": ["answer"],
        },
    },
}


@register_function("submit_answer", submit_answer_desc, ToolType.SYSTEM_CTL)
async def submit_answer(conn: "ConnectionHandler", answer: str):
    device_id = conn.device_id
    s = store.get(device_id)
    if s is None:
        return ActionResponse(
            action=Action.REQLLM,
            result="当前没有进行中的口算练习。如果孩子想练习，请调用 start_practice。",
        )
    qq = s["questions"][s["idx"]]
    got = generator.normalize_answer(answer, qq["kind"])
    if got is None:
        _bump_timer(conn, s)  # 孩子在积极说话，重置超时计时
        return ActionResponse(
            action=Action.REQLLM,
            result=(
                f"孩子的回答「{answer}」没有解析出数字或符号。"
                "如果原话里有明确的答案，提取出来重新调用 submit_answer；"
                "否则请温和地引导孩子再说一遍。"
            ),
        )
    correct = got == qq["answer"]

    if correct:
        praise = "巩固题也答对了，真棒！" if qq["role"] == "reinforce" else "答对了！"
        lead = f"{praise}请简短表扬一句，"
        return await _respond_next(conn, s, scored=True, lead=lead)

    if qq["role"] == "reinforce":  # 巩固题一次机会，不循环（#26 决议）
        material = explanations.build_material(qq)
        lead = (
            f"巩固题没答对，没关系。直接温柔地告诉孩子答案：{material['answer']}（{material['steps']}），"
        )
        return await _respond_next(conn, s, scored=False, lead=lead)

    if s["attempts"] == 0:  # 首错：鼓励重试，不透露答案（#23 决议）
        saved = store.save({**s, "attempts": 1, "timeout_skips": 0})
        _bump_timer(conn, saved)
        return ActionResponse(
            action=Action.REQLLM,
            result="答错了。请温和地说「没关系，再想想」鼓励孩子再算一次，不要透露答案也不要讲解。"
                   "孩子再次回答后调用 submit_answer。",
        )

    # 二错：讲解素材 + 巩固题（#26：素材给 LLM，数字事实为准，LLM 不算数）
    material = explanations.build_material(qq)
    reinforce = generator.TYPES[qq["type"]]["gen"](random.Random())
    while reinforce["text"] == qq["text"]:  # 巩固题避开原题
        reinforce = generator.TYPES[qq["type"]]["gen"](random.Random())
    questions = [
        *s["questions"][: s["idx"] + 1],
        {**reinforce, "role": "reinforce"},
        *s["questions"][s["idx"] + 1 :],
    ]
    saved = store.save({
        **s,
        "questions": questions,
        "idx": s["idx"] + 1,  # 推进到巩固题（原题已判完，answered 计数）
        "attempts": 0,
        "timeout_skips": 0,
        "answered": s["answered"] + 1,
        "main_no": s["main_no"] + 1,
        "streak": 0,  # 主题二错判负，连对清零（#29）
    })
    _bump_timer(conn, saved)
    _push_in_background(conn, saved)
    await _show_question(conn, saved)
    return ActionResponse(
        action=Action.REQLLM,
        result=(
            f"孩子第二次答错。请用简短、鼓励的语气按以下素材讲解（数字以素材为准，不要自行计算）："
            f"方法：{material['method']}；步骤：{material['steps']}；正确答案：{material['answer']}。"
            f"讲解完后读这道巩固题：{view_text(saved)}，孩子回答后调用 submit_answer。"
        ),
    )


end_practice_desc = {
    "type": "function",
    "function": {
        "name": "end_practice",
        "description": "当孩子主动表示不想继续练习（如「不想练了」「我要玩别的」）时调用，结束本轮。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


@register_function("end_practice", end_practice_desc, ToolType.SYSTEM_CTL)
async def end_practice(conn: "ConnectionHandler"):
    device_id = conn.device_id
    s = store.get(device_id)
    if s is None:
        return ActionResponse(action=Action.REQLLM, result="当前没有进行中的口算练习，自然收尾即可。")
    store.delete(device_id)
    _cancel_timer(device_id)
    _report_in_background(conn, s)
    return ActionResponse(
        action=Action.REQLLM,
        result=(
            f"练习结束，孩子已完成{s['answered']}/{s['total']}题，答对{s['score']}题。"
            "请简短收尾并鼓励孩子，不要追问练不练了。"
        ),
    )
