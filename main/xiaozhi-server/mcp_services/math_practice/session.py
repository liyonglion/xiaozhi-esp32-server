"""练习会话存储（设备级，一台设备 = 一个孩子 = 一场进行中的练习）。

Key 生命周期（#23 决议「三删一兜底」）：
- 正常完成 / 主动退出(end_practice) / 选择重新开始 → 立即删
- 被动中断（断连/跑题）→ 不主动删，TTL 24h 自然过期，供「继续上次的」恢复

ponytail: 进程内存 dict + 惰性过期。单进程裸机部署下与 Redis 等价；
需要跨重启续练或多进程时再换 Redis 后端——接口已收敛到 get/save/delete，替换面小。
"""
from __future__ import annotations

import time

SESSION_TTL = 24 * 3600


def new_session(device_id: str, questions: list[dict], total: int, preset: str = "") -> dict:
    now = time.time()
    return {
        "device_id": device_id,
        "questions": [{**qq, "role": "main"} for qq in questions],
        "total": total,
        "preset": preset,  # 供收尾上报练习记录（#24）
        "idx": 0,
        "main_no": 1,  # 当前主题序号（1-based，不含巩固题）
        "score": 0,
        "answered": 0,
        "attempts": 0,
        "started_at": now,
        "last_active": now,
    }


def view_text(s: dict) -> str:
    """当前题的屏显文本（≤20 字符预算，#22 调研约束）。"""
    qq = s["questions"][s["idx"]]
    if qq["role"] == "reinforce":
        return f"加练 {qq['text']}"
    return f"{s['main_no']}/{s['total']} {qq['text']}"


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}

    def get(self, device_id: str) -> dict | None:
        s = self._sessions.get(device_id)
        if s is None:
            return None
        if time.time() - s["last_active"] > SESSION_TTL:
            del self._sessions[device_id]
            return None
        return s

    def save(self, session: dict) -> dict:
        fresh = {**session, "last_active": time.time()}
        self._sessions[session["device_id"]] = fresh
        return fresh

    def delete(self, device_id: str) -> None:
        self._sessions.pop(device_id, None)


store = SessionStore()
