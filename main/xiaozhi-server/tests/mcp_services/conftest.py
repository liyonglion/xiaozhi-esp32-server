"""math_practice 测试的显示消息采集。

优先用真实 core.handle.sendAudioHandle（写入 conn.websocket.send，FakeWS 采集）；
仅当本地依赖缺失导入失败时才装 stub（直接写入 conn.sent），避免顶替真模块
导致其他测试（如 test_tts 经 reportHandle 导入 sendAudioMessage）失败。
"""
import sys
import types

try:
    import core.handle.sendAudioHandle  # noqa: F401
except Exception:
    _stub = types.ModuleType("core.handle.sendAudioHandle")
    _stub.__file__ = __file__

    async def send_display_message(conn, text):
        conn.sent.append({"type": "stt", "text": text})

    async def send_tts_message(conn, state, text=None):
        if text is not None:
            conn.sent.append({"type": "tts", "state": state, "text": text})

    _stub.send_display_message = send_display_message
    _stub.send_tts_message = send_tts_message
    sys.modules.setdefault("core.handle.sendAudioHandle", _stub)
