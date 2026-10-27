"""设备 Todo 清单：镜像上报（T1）+ 家长编辑下发闭环（spec #30 T2 / #32）。

设备 NVS 是清单唯一真值源；本模块挂在 MCP set_todos 调用的返回路径上，
把 receipt 中的全量清单异步上报 manager-api 存镜像（per-device FIFO 锁保序，
照 mathPractice 后台任务模式）。未注册该工具的旧固件根本不会发起调用，天然跳过。

T2 增两件基础设施（spec #30「服务端基础设施」）：
- 连接注册表：模块级 dict[mac→conn]，websocket 连接建立/断开处挂注册注销；
- 60s 同步循环（照 gc_manager 模式，app.py 挂载）：周期上报在线 mac 集合、
  扫 pending → 对在线设备经 MCP set_todos(replace) 整表下发 → receipt ok 清 pending；
  离线保留 pending，上线即达。
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from core.providers.tools.device_mcp import call_mcp_tool

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__

_report_tasks: set[asyncio.Task] = set()  # 持引用防 GC；fire-and-forget 上报
_locks: dict[str, asyncio.Lock] = {}  # per-device FIFO：上报按语音操作顺序落库
_connections: dict[str, "ConnectionHandler"] = {}  # 在线连接注册表（mac→conn）

# 下发期间挂在 conn 上的标记：抑制 T1 语音上报挂钩——下发的 receipt 由本模块
# 自行回执清 pending，再走语音上报会把旧内容回写镜像、来源错记 voice
_PUSHING_ATTR = "_todo_downlink_push"


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
    if getattr(conn, _PUSHING_ATTR, False):
        return  # 下发路径的回执由 _push_and_confirm 处理，不再触发语音上报
    todos = parse_receipt(raw_result)
    if todos is None:
        return
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
        try:
            while not self._stop_event.is_set():
                await run_sync_cycle()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
                    break
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as e:  # 循环兜底：单轮异常已各自吞掉，这里只防意外退出
            from config.logger import setup_logging

            setup_logging().bind(tag=TAG).error(f"todo 同步循环退出: {e}")


# app.py 挂载的全局单例
todo_sync_manager = TodoSyncManager()


async def run_sync_cycle() -> None:
    """单轮同步：上报在线集合 → 拉 pending → 逐台在线设备整表下发（pending 序即下发序）。"""
    from config import manage_api_client

    try:
        await manage_api_client.report_online_macs(list(_connections))
    except Exception as e:
        _log("warning", f"todo 在线集合上报中断: {e}")

    try:
        pending = await manage_api_client.get_todo_pending()
    except Exception as e:
        _log("warning", f"todo 待下发清单拉取中断: {e}")
        return
    if not pending:
        return

    for row in pending:
        mac = row.get("mac")
        conn = _connections.get(mac) if mac else None
        if conn is None:
            continue  # 离线：pending 保留，上线后下一轮即达
        try:
            await _push_and_confirm(conn, row.get("items") or [])
        except Exception as e:  # 单台失败不挡后续设备，也不炸循环
            _log("warning", f"todo 下发 {mac} 中断: {e}")


async def _push_and_confirm(conn: "ConnectionHandler", items: list) -> None:
    """对单台在线设备 set_todos(replace) 整表下发；receipt ok 才回执清 pending。

    旧固件（未注册 set_todos）/ MCP 未就绪：静默跳过（照 math_practice has_tool 门槛）。
    """
    mcp = getattr(conn, "mcp_client", None)
    if mcp is None or not mcp.has_tool("set_todos"):
        return
    if not await mcp.is_ready():
        return

    setattr(conn, _PUSHING_ATTR, True)
    try:
        raw = await call_mcp_tool(
            conn, mcp, "set_todos",
            {"action": "replace", "text": json.dumps(items, ensure_ascii=False)},
        )
    finally:
        setattr(conn, _PUSHING_ATTR, False)

    todos = parse_receipt(raw)
    if todos is None:
        return  # 设备拒绝（ok:false / 非契约）：保留 pending，下一轮重试
    from config import manage_api_client

    try:
        await manage_api_client.report_todo_delivered(conn.device_id, todos)
    except Exception as e:
        _log("warning", f"todo 送达回执中断 {conn.device_id}: {e}")  # 回执丢失由下一轮重发兜底


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
