"""设备 Todo 清单：镜像上报（T1）+ 家长编辑下发闭环（T2）+ 截止提醒（spec #30 T4 / #34）。

设备 NVS 是清单唯一真值源；本模块挂在 MCP set_todos 调用的返回路径上，
把 receipt 中的全量清单异步上报 manager-api 存镜像（per-device FIFO 锁保序，
照 mathPractice 后台任务模式）。未注册该工具的旧固件根本不会发起调用，天然跳过。

T2 增两件基础设施（spec #30「服务端基础设施」）：
- 连接注册表：模块级 dict[mac→conn]，websocket 连接建立/断开处挂注册注销；
- 60s 同步循环（照 gc_manager 模式，app.py 挂载）：周期上报在线 mac 集合、
  扫 pending → 对在线设备经 MCP set_todos(replace) 整表下发 → receipt ok 清 pending；
  离线保留 pending，上线即达。

T4 截止提醒：server 只做翻译与簿记，不做提醒扫描、不推 TTS——
- 翻译：items 的服务端侧 due（HH:MM）→ due−1h / due−30m 两个提醒点，经设备已有
  self.clock.set_alarm 设置（静默时段内的点不设；deadline<=now 的过期点过滤后才调
  set_alarm，防设备把已过时刻顺延成次日幽灵闹钟）；
- 簿记：模块级 mac→[{text,kind,time,message,id}]；下发成功后先 cancel 旧映射再按最新
  items 重设；语音 receipt 里任务完成/文本消失（删除/改写）→ 按簿记 cancel；
- 对账：60s 循环对新上线连接用 self.clock.list 以 message 为匹配键比对——簿记有而设备
  没有（设备重启丢闹钟）→ 过期过滤后重设；设备有而簿记没有（server 重启）→ 收养重建簿记；
- 重试：set_alarm 返回「时间未同步」error 视为可重试（簿记 id 置 None 不确认，下轮循环再设）。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import TYPE_CHECKING

from core.providers.tools.device_mcp import call_mcp_tool

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__

_report_tasks: set[asyncio.Task] = set()  # 持引用防 GC；fire-and-forget 上报
_locks: dict[str, asyncio.Lock] = {}  # per-device FIFO：上报按语音操作顺序落库
_connections: dict[str, "ConnectionHandler"] = {}  # 在线连接注册表（mac→conn）

# 下发抑制按调用粒度：mcp_handler 的 receipt 挂钩在发起调用的那个 asyncio task 里同步触发，
# 记录下发自身的 task 即可精确区分——下发在途（最长 30s）期间孩子的语音 receipt 不受牵连
_pushing_tasks: set[asyncio.Task] = set()


def parse_receipt(raw: str) -> list | None:
    """解析 set_todos receipt：成功返回规整后的全量清单，非契约返回 None。

    item 结构不可扩（{"text": str, "done": bool}），异构项剔除，不整体拒绝——
    设备是真值源，坏一项不丢整表。
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("ok") is not True:
        return None
    todos = data.get("todos")
    if not isinstance(todos, list):
        return None
    return [
        {"text": t["text"], "done": t["done"]}
        for t in todos
        if isinstance(t, dict) and isinstance(t.get("text"), str) and isinstance(t.get("done"), bool)
    ]


def on_set_todos_receipt(conn: "ConnectionHandler", raw_result: str) -> None:
    """set_todos 返回路径挂钩入口（mcp_handler 调用）：receipt 无效静默返回。"""
    if asyncio.current_task() in _pushing_tasks:
        return  # 下发自身调用的回执由 _push_and_confirm 处理，不再触发语音上报
    todos = parse_receipt(raw_result)
    if todos is None:
        return
    _drop_finished_alarms(conn.device_id, todos)  # T4：完成/删除/改写 → 按簿记 cancel 对应提醒
    task = asyncio.create_task(_report_locked(conn, todos))
    _report_tasks.add(task)
    task.add_done_callback(_report_tasks.discard)


# ───────────────────────── 连接注册表（websocket 建立断开处挂钩） ─────────────────────────

def register_connection(mac: str, conn: "ConnectionHandler") -> None:
    _connections[mac] = conn


def unregister_connection(mac: str, conn: "ConnectionHandler") -> None:
    """身份守卫注销：重连后新句柄已顶替时，旧连接的关闭不得误删新注册。"""
    if _connections.get(mac) is conn:
        _connections.pop(mac, None)


def connection_for(mac: str) -> "ConnectionHandler | None":
    return _connections.get(mac)


# ───────────────────────── 60s 下发同步循环（gc_manager 模式） ─────────────────────────

class TodoSyncManager:
    """asyncio 定时循环：先跑一轮再等间隔（保存后最坏一个周期内送达，在线设备一分钟内更新）。"""

    def __init__(self, interval_seconds: int = 60):
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await run_sync_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # 单轮未预见异常只记日志，循环继续（防一次性 bug 永久停摆）
                _log("error", f"todo 同步单轮异常: {e}")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
                break
            except asyncio.TimeoutError:
                pass


# app.py 挂载的全局单例
todo_sync_manager = TodoSyncManager()


async def run_sync_cycle() -> None:
    """单轮同步：上报在线集合 → 拉 pending → 逐台在线设备整表下发（pending 序即下发序）→ 提醒对账面。"""
    from config import manage_api_client

    try:
        await manage_api_client.report_online_macs(list(_connections))
    except Exception as e:
        _log("warning", f"todo 在线集合上报中断: {e}")

    try:
        pending = await manage_api_client.get_todo_pending()
    except Exception as e:
        pending = None
        _log("warning", f"todo 待下发清单拉取中断: {e}")

    if pending:
        for row in pending:
            mac = row.get("mac")
            conn = _connections.get(mac) if mac else None
            if conn is None:
                continue  # 离线：pending 保留，上线后下一轮即达
            quiet = (row.get("quietStart") or DEFAULT_QUIET_START, row.get("quietEnd") or DEFAULT_QUIET_END)
            _quiet_cfg[mac] = quiet  # 提醒翻译的设备级静默配置随 pending 行捎带
            try:
                await _push_and_confirm(conn, row.get("items") or [])
            except Exception as e:  # 单台失败不挡后续设备，也不炸循环
                _log("warning", f"todo 下发 {mac} 中断: {e}")

    await _alarm_ensure_pass()


async def _push_and_confirm(conn: "ConnectionHandler", items: list) -> None:
    """对单台在线设备 set_todos(replace) 整表下发；receipt ok 才回执清 pending。

    旧固件（未注册 set_todos）/ MCP 未就绪：静默跳过（照 math_practice has_tool 门槛）。
    """
    mcp = getattr(conn, "mcp_client", None)
    if mcp is None or not mcp.has_tool("set_todos"):
        return
    if not await mcp.is_ready():
        return

    task = asyncio.current_task()
    _pushing_tasks.add(task)  # 只抑制本调用：语音 receipt 在别的 task 里触发，不受影响
    try:
        raw = await call_mcp_tool(
            conn, mcp, "set_todos",
            {"action": "replace", "text": json.dumps(strip_due(items), ensure_ascii=False)},
        )
    finally:
        _pushing_tasks.discard(task)

    todos = parse_receipt(raw)
    if todos is None:
        return  # 设备拒绝（ok:false / 非契约）：保留 pending，下一轮重试
    from config import manage_api_client

    try:
        await manage_api_client.report_todo_delivered(conn.device_id, todos)
    except Exception as e:
        _log("warning", f"todo 送达回执中断 {conn.device_id}: {e}")  # 回执丢失由下一轮重发兜底
    await _reset_alarms(conn, items, todos)  # T4：送达成功 → 按最新 items（含 due）重设当日提醒闹钟


def _log(level: str, msg: str) -> None:
    """旁路日志：连接对象不可用时（循环上下文无 conn）落到全局 logger。"""
    try:
        from config.logger import setup_logging

        getattr(setup_logging().bind(tag=TAG), level)(msg)
    except Exception:
        pass


async def _report_locked(conn: "ConnectionHandler", todos: list) -> None:
    """per-device FIFO 锁内上报：语音操作顺序即落库顺序，乱序会让旧状态覆盖新状态。"""
    try:
        async with _device_lock(conn.device_id):
            from config import manage_api_client

            await manage_api_client.report_todo_list(conn.device_id, todos)
    except Exception as e:  # 上报是旁路，绝不影响语音主流程
        try:
            conn.logger.bind(tag=TAG).warning(f"todo 镜像上报中断: {e}")
        except Exception:
            pass


def _device_lock(device_id: str) -> asyncio.Lock:
    if len(_locks) > 1024:
        # ponytail: 粗上限防连接churn膨胀。只清未被持有的锁，在途任务不受影响；
        # 真到千设备量级再换 LRU。
        held = {k: v for k, v in _locks.items() if v.locked()}
        _locks.clear()
        _locks.update(held)
    return _locks.setdefault(device_id, asyncio.Lock())


# ───────────────────────── T4：截止提醒（翻译 + 簿记 + 对账，spec #30 / #34） ─────────────────────────

REMINDER_TEXTS = {"1h": "还有1小时到截止:{text}", "30m": "还有半小时到截止:{text}"}
DEFAULT_QUIET_START = "21:00"
DEFAULT_QUIET_END = "07:00"

# 设备 MCP 工具名经 sanitize_tool_name 点号转下划线（mcp_client.tools 以净化名为键）
CLOCK_SET_ALARM = "self_clock_set_alarm"
CLOCK_CANCEL = "self_clock_cancel"
CLOCK_LIST = "self_clock_list"

_alarms: dict[str, list[dict]] = {}  # 簿记 mac→[{text,kind,time,message,id}]；id=None 未确认（待重试）
_quiet_cfg: dict[str, tuple[str, str]] = {}  # mac→(quiet_start,quiet_end)，随 pending 行捎带刷新
_ensured_conns: dict[str, "ConnectionHandler"] = {}  # mac→已对账连接（重连=新对象→重新对账）
_bg_tasks: set[asyncio.Task] = set()  # fire-and-forget 闹钟 cancel（持引用防 GC）


def _hm_to_min(hm) -> int | None:
    try:
        h, m = hm.split(":")
        minutes = int(h) * 60 + int(m)
    except (AttributeError, ValueError):
        return None
    return minutes if 0 <= minutes < 1440 else None


def _min_to_hm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _now_min() -> int:
    return datetime.now().hour * 60 + datetime.now().minute


def translate_due(due, text: str, *, now_hm: str | None = None,
                  quiet_start: str = DEFAULT_QUIET_START, quiet_end: str = DEFAULT_QUIET_END) -> list[dict]:
    """due(HH:MM) → 提醒点 [{kind,time,message}]：due−1h 与 due−30m 两档，按时间序。

    跨零点语义：due 当日读数 < now → 截止在次日（23:50 设次日 01:00），+1440 再比较，
    否则次日凌晨的提醒点全被当过期点过滤，65 分钟后的截止永远没有提醒。
    过滤顺序（spec #30「截止提醒语义」）：deadline<=now 的过期点直接丢弃——设备对已过
    HH:MM 会静默顺延明天，不过滤即产生次日幽灵闹钟；落静默时段 [quiet_start, quiet_end)
    （支持跨零点）的点不设。非法 due 返回空。
    """
    due_min = _hm_to_min(due)
    if due_min is None:
        return []
    now_min = _hm_to_min(now_hm) if now_hm is not None else _now_min()
    if due_min < now_min:
        due_min += 1440  # 截止已过当日读数 → 次日（now 之前 +1440 的点保证未来）
    qs, qe = _hm_to_min(quiet_start), _hm_to_min(quiet_end)
    specs = []
    for kind, delta in (("1h", 60), ("30m", 30)):
        point = due_min - delta
        if point <= now_min:  # 含负值（due<60 时 due-60<0<now）：过期点不设
            continue
        if qs is not None and qe is not None:
            tod = point % 1440  # 静默按时段判断（次日 00:30 与当日 00:30 同静默）
            in_quiet = qs <= tod < qe if qs <= qe else tod >= qs or tod < qe
            if in_quiet:
                continue
        specs.append({"kind": kind, "time": _min_to_hm(point % 1440),
                      "message": REMINDER_TEXTS[kind].format(text=text)})
    return specs


def parse_reminder_message(message) -> tuple[str, str] | None:
    """播报文本 → (task_text, kind)：message 是簿记与对账恢复共用的匹配键。"""
    if not isinstance(message, str):
        return None
    for kind, prefix in (("1h", "还有1小时到截止:"), ("30m", "还有半小时到截止:")):
        if message.startswith(prefix) and len(message) > len(prefix):
            return message[len(prefix):], kind
    return None


def strip_due(items: list) -> list[dict]:
    """设备契约 {text,done} 不得漂移：下发前剥离服务端侧字段 due（外层键一并收窄）。"""
    return [{"text": i.get("text"), "done": i.get("done")} for i in items if isinstance(i, dict)]


async def _clock_call(conn: "ConnectionHandler", tool: str, args: dict):
    """经 MCP 调设备闹钟工具；旧固件未注册 self.clock.* / 未就绪 → None（静默跳过，照 math_practice 门槛）。"""
    mcp = getattr(conn, "mcp_client", None)
    if mcp is None or not mcp.has_tool(tool) or not await mcp.is_ready():
        return None
    return await call_mcp_tool(conn, mcp, tool, args)


async def _set_reminder_alarm(conn: "ConnectionHandler", rec: dict) -> bool:
    """设单个提醒闹钟并落簿记 id。True=已确认或待重试（时间未同步，id 置 None，下轮循环再设）；
    False=应放弃该记录（其它错误/工具不可用）。"""
    try:
        raw = await _clock_call(conn, CLOCK_SET_ALARM, {"time": rec["time"], "message": rec["message"]})
    except Exception as e:
        if "not synced" in str(e).lower():
            rec["id"] = None  # 设备时间未同步：可重试，簿记未确认
            return True
        _log("warning", f"todo 提醒闹钟设置失败 {conn.device_id}: {e}")
        return False
    if raw is None:
        return False
    try:
        rec["id"] = json.loads(raw).get("id")
    except (json.JSONDecodeError, AttributeError):
        return False
    return True


async def _cancel_alarm(conn: "ConnectionHandler", alarm_id) -> None:
    try:
        await _clock_call(conn, CLOCK_CANCEL, {"id": alarm_id})
    except Exception:
        pass  # id 已不在设备上（响过/已取消/重启丢失）=目标已达成


async def _reset_alarms(conn: "ConnectionHandler", items: list, echo: list) -> None:
    """admin 保存 / 每日重建下发成功后：先 cancel 该设备全部旧映射，再按最新 items（含 due）设当日闹钟。"""
    mac = conn.device_id
    for rec in _alarms.pop(mac, []):
        if rec.get("id") is not None:
            await _cancel_alarm(conn, rec["id"])
    echo_done = {t["text"]: t["done"] for t in echo}
    quiet = _quiet_cfg.get(mac, (DEFAULT_QUIET_START, DEFAULT_QUIET_END))
    records = []
    for it in items:
        if not isinstance(it, dict):
            continue
        text, due = it.get("text"), it.get("due")
        if not due or echo_done.get(text) is not False:
            continue  # 无截止 / 设备上已完成 / 文本不在回执（送达期间被改写）→ 不设
        records.extend({**spec, "text": text, "id": None}
                       for spec in translate_due(due, text, quiet_start=quiet[0], quiet_end=quiet[1]))
    kept = [r for r in records if await _set_reminder_alarm(conn, r)]
    _alarms[mac] = kept


def _drop_finished_alarms(mac: str, todos: list) -> None:
    """语音 receipt 联动：任务勾选完成或文本消失（删除/改写=remove+add）→ 按簿记 cancel 对应闹钟。
    簿记同步收缩，cancel 异步执行（绝不阻塞语音主流程）。"""
    records = _alarms.get(mac)
    if not records:
        return
    state = {t["text"]: t["done"] for t in todos}
    keep = [r for r in records if state.get(r["text"]) is False]
    dropped = [r for r in records if state.get(r["text"]) is not False]
    _alarms[mac] = keep
    conn = _connections.get(mac)
    if dropped and conn is not None:
        _spawn(_cancel_booked(conn, dropped))


async def _cancel_booked(conn: "ConnectionHandler", records: list) -> None:
    for r in records:
        if r.get("id") is not None:
            await _cancel_alarm(conn, r["id"])


async def _reconcile_alarms(mac: str, conn: "ConnectionHandler") -> None:
    """上线对账：self.clock.list 与簿记互相补齐——message 为匹配键。
    簿记有而设备没有（设备重启丢闹钟）→ 过期过滤后重设；设备有而簿记没有（server 重启）→ 收养重建。"""
    try:
        raw = await _clock_call(conn, CLOCK_LIST, {})
    except Exception as e:
        _log("warning", f"todo 提醒对账 list 失败 {mac}: {e}")
        return  # 不标记已对账：下轮循环重试
    if raw is None:
        _ensured_conns[mac] = conn
        return
    try:
        listed = json.loads(raw).get("alarms") or []
    except (json.JSONDecodeError, AttributeError):
        listed = []
    on_device = {a["message"]: a for a in listed
                 if isinstance(a, dict) and isinstance(a.get("message"), str)}
    records = _alarms.setdefault(mac, [])
    for msg, alarm in on_device.items():  # 收养：重建 server 重启丢失的簿记
        parsed = parse_reminder_message(msg)
        if parsed is None or any(r["message"] == msg for r in records):
            continue
        ring = str(alarm.get("ring_at") or "")
        records.append({"text": parsed[0], "kind": parsed[1],
                        "time": ring.split(" ")[-1] if ":" in ring else None,
                        "message": msg, "id": alarm.get("id")})
    now_min = _now_min()
    for rec in list(records):
        if rec["message"] in on_device and rec.get("id") is not None:
            continue  # 设备上在位：无需动作
        point = _hm_to_min(rec.get("time"))
        if point is None or point <= now_min:
            records.remove(rec)  # 提醒点已过：不重设（重设会被设备顺延成次日幽灵闹钟）
            continue
        if not await _set_reminder_alarm(conn, rec):
            records.remove(rec)
    _ensured_conns[mac] = conn


async def _alarm_ensure_pass() -> None:
    """60s 循环的提醒面：新上线连接（重连/重启）对账；簿记存在未确认记录（时间未同步）重试。"""
    for mac, conn in list(_connections.items()):
        records = _alarms.get(mac) or []
        if _ensured_conns.get(mac) is conn and all(r.get("id") is not None for r in records):
            continue
        try:
            await _reconcile_alarms(mac, conn)
        except Exception as e:
            _log("warning", f"todo 提醒对账 {mac} 中断: {e}")


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
