"""设备 Todo 清单镜像上报（spec #30 T1 / #31）。

设备 NVS 是清单唯一真值源；本模块挂在 MCP set_todos 调用的返回路径上，
把 receipt 中的全量清单异步上报 manager-api 存镜像（per-device FIFO 锁保序，
照 mathPractice 后台任务模式）。未注册该工具的旧固件根本不会发起调用，天然跳过。
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__

_report_tasks: set[asyncio.Task] = set()  # 持引用防 GC；fire-and-forget 上报
_locks: dict[str, asyncio.Lock] = {}  # per-device FIFO：上报按语音操作顺序落库


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
    todos = parse_receipt(raw_result)
    if todos is None:
        return
    task = asyncio.create_task(_report_locked(conn, todos))
    _report_tasks.add(task)
    task.add_done_callback(_report_tasks.discard)


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
