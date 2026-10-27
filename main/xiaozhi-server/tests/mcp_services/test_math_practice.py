"""口算练习测试：出题器独立复检（不超纲）+ 讲解素材 + 会话存储 + 插件全链路。

出题器部分自 research/math-generator 原型的 check 移植（200 题/型）。
"""
import asyncio
import contextlib
import json
import queue
import random
import time
from types import SimpleNamespace

import pytest
from loguru import logger

from mcp_services.math_practice import explanations, generator
from mcp_services.math_practice.session import SESSION_TTL, SessionStore, new_session, view_text
from plugins_func.functions import math_practice as mp
from plugins_func.register import Action

N = 200  # 每题型抽检量


# ───────────────────────── 出题器独立复检 ─────────────────────────

CHECKS = {
    "A1": lambda m, ans: 0 <= m["a"] <= 5 and 0 <= m["b"] <= 5 and m["a"] + m["b"] <= 5 and ans == m["a"] + m["b"],
    "A2": lambda m, ans: m["a"] + m["b"] <= 10 and ans == m["a"] + m["b"],
    "A3": lambda m, ans: 10 <= m["a"] <= 19 and m["b"] <= 9 and m["a"] % 10 + m["b"] < 10 and ans == m["a"] + m["b"],
    "A4": lambda m, ans: m["a"] <= 9 and m["b"] <= 9 and 10 <= m["a"] + m["b"] <= 18 and ans == m["a"] + m["b"],
    "A5": lambda m, ans: 1 <= m["b"] <= 9 and m["a"] + m["b"] <= 50 and ans == m["a"] + m["b"],
    "A6": lambda m, ans: 10 <= m["a"] <= 99 and 1 <= m["b"] <= 9 and m["a"] + m["b"] <= 100 and ans == m["a"] + m["b"],
    "A7": lambda m, ans: 10 <= m["a"] <= 99 and 10 <= m["b"] <= 99 and m["a"] + m["b"] <= 100 and ans == m["a"] + m["b"],
    "S1": lambda m, ans: m["a"] <= 5 and 0 <= m["b"] <= m["a"] and ans == m["a"] - m["b"],
    "S2": lambda m, ans: m["a"] <= 10 and 0 <= m["b"] <= m["a"] and ans == m["a"] - m["b"],
    "S3": lambda m, ans: 11 <= m["a"] <= 19 and m["b"] <= m["a"] % 10 and ans == m["a"] - m["b"],
    "S4": lambda m, ans: 11 <= m["a"] <= 19 and m["a"] % 10 < m["b"] <= 9 and ans == m["a"] - m["b"] >= 1,
    "S5": lambda m, ans: m["b"] <= 9 and m["a"] <= 50 and m["a"] > m["b"] and ans == m["a"] - m["b"],
    "S6": lambda m, ans: 10 <= m["a"] <= 99 and m["b"] <= 9 and m["a"] > m["b"] and ans == m["a"] - m["b"],
    "S7": lambda m, ans: 10 <= m["b"] <= 90 and m["b"] % 10 == 0 and m["a"] <= 99 and m["a"] > m["b"] and ans == m["a"] - m["b"],
    "S8": lambda m, ans: 10 <= m["b"] <= 99 and 10 <= m["a"] <= 100 and m["a"] > m["b"] and ans == m["a"] - m["b"],
    "M1": lambda m, ans: 1 <= m["a"] <= 6 and 1 <= m["b"] <= 6 and ans == m["a"] * m["b"],
    "M2": lambda m, ans: 1 <= m["a"] <= 9 and 1 <= m["b"] <= 9 and ans == m["a"] * m["b"],
    "M3": lambda m, ans: m["prod"] % m["a"] == 0 and 2 <= m["a"] <= 9 and 2 <= ans <= 9 and ans == m["prod"] // m["a"],
    "D1": lambda m, ans: 2 <= m["d"] <= 6 and m["dividend"] % m["d"] == 0 and m["dividend"] <= 54 and 1 <= ans <= 9 and ans == m["dividend"] // m["d"],
    "D2": lambda m, ans: 2 <= m["d"] <= 9 and m["dividend"] % m["d"] == 0 and m["dividend"] <= 81 and 1 <= ans <= 9 and ans == m["dividend"] // m["d"],
    "ADJ100": lambda m, ans: (m["side"] == "back" and 0 <= m["x"] <= 99 and ans == m["x"] + 1)
                             or (m["side"] == "front" and 1 <= m["x"] <= 100 and ans == m["x"] - 1 and ans >= 0),
    "PAT20": lambda m, ans: len(m["seq"]) == 5
             and ((m["mode"] == "alt"
                   and m["seq"][0] != m["seq"][1] and m["seq"][2:4] == m["seq"][:2]
                   and m["seq"][4] == m["seq"][0] and ans == m["seq"][0])
                  or (m["mode"] == "arith"
                      and m["seq"][4] <= 20 and m["seq"][0] >= 0
                      and len({m["seq"][i + 1] - m["seq"][i] for i in range(4)}) == 1
                      and ans == m["seq"][4])),
    "DEC": lambda m, ans: (m["ask"] == "part" and 2 <= m["n"] <= 10 and 1 <= m["p"] < m["n"] and ans == m["n"] - m["p"])
                          or (m["ask"] == "total" and m["p"] >= 1 and m["q"] >= 1 and m["p"] + m["q"] <= 10 and ans == m["p"] + m["q"]),
}
for _r in (5, 10, 100):
    CHECKS[f"CMP{_r}"] = (lambda r: lambda m, ans: 0 <= m["x"] <= r and 0 <= m["y"] <= r
                           and ans == (">" if m["x"] > m["y"] else "<" if m["x"] < m["y"] else "="))(_r)


class TestGenerator:
    def test_all_types_within_bounds(self):
        for tid, t in generator.TYPES.items():
            rng = random.Random(hash(tid) % 2**31)
            for _ in range(N):
                item = t["gen"](rng)
                assert CHECKS[tid](item["meta"], item["answer"]), f"{tid} 超纲/算错: {item}"
                assert item["kind"] == t["kind"]
                if item["kind"] == "int":
                    assert 0 <= item["answer"] <= 100
                else:
                    assert item["answer"] in (">", "<", "=")
                assert len(item["text"]) <= 20, f"{tid} 题面超 20 字符: {item['text']}"

    def test_cmp_symbols_balanced(self):
        seen = {generator.TYPES["CMP10"]["gen"](random.Random(i))["answer"] for i in range(60)}
        assert seen == {">", "<", "="}

    def test_dedup_and_zero_limit(self):
        rng = random.Random(1)
        set_a = generator.generate_practice(["A2"], 20, rng)
        assert len({generator.canonical_key(i) for i in set_a}) == 20
        assert generator.canonical_key({"type": "A2", "meta": {"a": 3, "b": 5}}) == \
            generator.canonical_key({"type": "A2", "meta": {"a": 5, "b": 3}})
        zs = generator.generate_practice(["A1", "S1"], 10, rng)
        assert len(zs) == 10 and sum(generator.has_zero_operand(i) for i in zs) <= 1

    def test_normalize(self):
        for spoken, want in [("12", 12), ("十二", 12), ("一十二", 12), ("二十", 20), ("十五", 15),
                             ("一百", 100), ("零", 0), ("两", 2), ("10。", 10), ("一百零一", None), ("十二岁", None)]:
            assert generator.normalize_answer(spoken, "int") == want, spoken
        for spoken, want in [("大于号", ">"), ("大于", ">"), ("＞", ">"), ("小于号", "<"),
                             ("等于", "="), ("等于号", "="), ("一样", "="), ("相等", "="), ("差不多", None)]:
            assert generator.normalize_answer(spoken, "sym") == want, spoken

    def test_cn_int(self):
        assert generator.cn_int(3) == "三"
        assert generator.cn_int(10) == "十"
        assert generator.cn_int(15) == "十五"
        assert generator.cn_int(21) == "二十一"
        assert generator.cn_int(40) == "四十"
        assert generator.cn_int(81) == "八十一"

    def test_presets_and_determinism(self):
        for name, ids in generator.PRESETS.items():
            assert all(i in generator.TYPES for i in ids), name
            assert len(generator.generate_practice(ids, 10, random.Random(7))) == 10, name
        assert generator.FALLBACK_PRESET in generator.PRESETS
        assert "A1" not in generator.PRESETS["g1a"]  # R1 决议
        a = [i["text"] for i in generator.generate_practice(generator.PRESETS["g1a"], 5, random.Random(7))]
        b = [i["text"] for i in generator.generate_practice(generator.PRESETS["g1a"], 5, random.Random(7))]
        assert a == b


class TestExplanations:
    def test_carry_add_picks_big_by_value(self):
        """47+8 须看大数 47、拆 8（按个位会把 8 当大数，讲解错误）。"""
        m = explanations.build_material({"type": "A6", "kind": "int", "answer": 55,
                                         "text": "47+8=", "meta": {"a": 47, "b": 8}})
        assert "看大数47，把8拆成3和5" in m["steps"]
        assert "47+3=50" in m["steps"] and "50+5=55" in m["steps"]

    def test_every_type_has_material(self):
        for tid, t in generator.TYPES.items():
            rng = random.Random(hash(tid) % 2**31)
            for _ in range(30):
                item = t["gen"](rng)
                mat = explanations.build_material(item)
                assert mat["method"] and mat["steps"], (tid, mat)
                if item["kind"] == "int":
                    assert str(item["answer"]) in mat["steps"], (tid, mat)
                elif item["answer"] != "=":
                    assert item["answer"] in mat["steps"], (tid, mat)

    def test_carry_add_ten(self):
        item = {"type": "A4", "text": "8+9=", "answer": 17, "kind": "int", "meta": {"a": 8, "b": 9}}
        mat = explanations.build_material(item)
        assert mat["method"] == "凑十法"
        assert "9+1=10" in mat["steps"] and "10+7=17" in mat["steps"]

    def test_borrow_sub(self):
        item = {"type": "S4", "text": "15-7=", "answer": 8, "kind": "int", "meta": {"a": 15, "b": 7}}
        mat = explanations.build_material(item)
        assert mat["method"] == "破十法"
        assert "10-7=3" in mat["steps"] and "3+5=8" in mat["steps"]

    def test_mult_table(self):
        item = {"type": "M2", "text": "3×7=", "answer": 21, "kind": "int", "meta": {"a": 3, "b": 7}}
        mat = explanations.build_material(item)
        assert mat["method"] == "乘法口诀" and "三七二十一" in mat["steps"]


class TestSessionStore:
    def test_lifecycle(self):
        st = SessionStore()
        qs = generator.generate_practice(generator.PRESETS["g1a"], 3, random.Random(1))
        s = new_session("dev1", qs, 3)
        assert all(q["role"] == "main" for q in s["questions"])
        assert view_text(s) == f"1/3 {qs[0]['text']}"
        saved = st.save(s)
        assert st.get("dev1")["idx"] == 0 and st.get("dev1")["last_active"] >= s["started_at"]
        st.delete("dev1")
        assert st.get("dev1") is None

    def test_ttl_expiry(self):
        st = SessionStore()
        qs = generator.generate_practice(generator.PRESETS["g1a"], 3, random.Random(1))
        s = new_session("dev2", qs, 3)
        st.save(s)
        st._sessions["dev2"]["last_active"] = time.time() - SESSION_TTL - 1
        assert st.get("dev2") is None


# ───────────────────────── 插件全链路（FakeConn） ─────────────────────────

class FakeTTS:
    def __init__(self):
        self.tts_text_queue = queue.SimpleQueue()
        self.stored = []

    def store_tts_text(self, sentence_id, text):
        self.stored.append(text)


class FakeWS:
    def __init__(self, conn):
        self._conn = conn

    async def send(self, message):
        m = json.loads(message)
        self._conn.sent.append(m)
        # 设备端 MCP 响应回环：tools/call 请求立即结算 future（真路径经 call_mcp_tool）
        mc = getattr(self._conn, "mcp_client", None)
        if m.get("type") == "mcp" and mc is not None:
            p = m["payload"]
            if p.get("method") == "tools/call":
                fut = mc.futures.get(p["id"])
                if fut and not fut.done():
                    fut.set_result({"content": [{"text": "ok"}]})


class FakeMCPClient:
    """设备 MCP 客户端假件：注册 update_progress 工具并按 id 结算调用。"""

    def __init__(self, tools=("update_progress",)):
        self.tools = {name: {"description": name, "inputSchema": {}} for name in tools}
        self.name_mapping = {}
        self.ready = True
        self.futures = {}

    def has_tool(self, name):
        return name in self.tools

    async def is_ready(self):
        return self.ready

    async def get_next_id(self):
        return len(self.futures) + 1

    async def register_call_result_future(self, tid, future):
        self.futures[tid] = future

    async def cleanup_call_result_future(self, tid):
        self.futures.pop(tid, None)


def make_conn(device_id="AA:BB:CC:DD:EE:FF", nudge=0, count=5, token="", mcp=None):
    conn = SimpleNamespace(
        device_id=device_id,
        config={"plugins": {"math_practice": {
            "count": count, "nudge_seconds": nudge, "progress_token": token,
        }}},
        session_id="s1", sentence_id=1, intent_type="function_call",
        sent=[], logger=logger,
    )
    conn.tts = FakeTTS()
    conn.websocket = FakeWS(conn)
    conn.features = {"mcp": mcp is not None}
    conn.mcp_client = mcp
    return conn


def stt_views(conn):
    return [m["text"] for m in conn.sent if m.get("type") == "stt"]


def wrong_for(q):
    if q["kind"] == "int":
        return str(q["answer"] + 1) if q["answer"] < 100 else "99"
    return "大于号" if q["answer"] != ">" else "小于号"


@pytest.fixture(autouse=False)
def _real_sleep(monkeypatch):
    """顶层 conftest 把 asyncio.sleep 换成了不 yield 的空操作（提速重试循环），
    计时器/等待类测试需要真实等待：用 executor 实现的真 sleep 替换回来。"""

    async def _real_sleep(seconds):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, time.sleep, min(seconds, 0.3))

    monkeypatch.setattr(asyncio, "sleep", _real_sleep)


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    for task in list(mp._timers.values()):  # loop 可能已随测试关闭，cancel 兜异常
        with contextlib.suppress(RuntimeError):
            task.cancel()
    mp._timers.clear()
    for task in list(mp._report_tasks):
        with contextlib.suppress(RuntimeError):
            task.cancel()
    mp._report_tasks.clear()
    mp.store._sessions.clear()
    mp._last_streak_end.clear()
    mp._push_locks.clear()


class TestPluginFlow:
    async def test_start_shows_first_question(self):
        conn = make_conn()
        r = await mp.start_practice(conn, difficulty="一年级上")
        assert r.action == Action.REQLLM and "第一题" in r.result
        s = mp.store.get(conn.device_id)
        assert s is not None and s["total"] == 5 and len(s["questions"]) == 5
        assert any(v.startswith("1/5") for v in stt_views(conn))

    async def test_full_flow_with_reinforce(self):
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)

        r = await mp.submit_answer(conn, str(s["questions"][0]["answer"]))
        assert "答对" in r.result
        s = mp.store.get(conn.device_id)
        assert s["score"] == 1 and s["idx"] == 1 and s["answered"] == 1
        assert any(v.startswith("2/5") for v in stt_views(conn))

        q2 = s["questions"][1]
        r = await mp.submit_answer(conn, wrong_for(q2))
        assert "再想想" in r.result
        assert mp.store.get(conn.device_id)["attempts"] == 1

        r = await mp.submit_answer(conn, wrong_for(q2))
        assert "方法" in r.result and "加练" in r.result
        s = mp.store.get(conn.device_id)
        assert len(s["questions"]) == 6 and s["questions"][s["idx"]]["role"] == "reinforce"
        assert s["answered"] == 2 and s["main_no"] == 3

        r = await mp.submit_answer(conn, wrong_for(s["questions"][s["idx"]]))
        assert "巩固题没答对" in r.result
        s = mp.store.get(conn.device_id)
        assert s["questions"][s["idx"]]["role"] == "main"
        assert any(v.startswith("3/5") for v in stt_views(conn))

        # 答完剩余主题题收尾：q1 对、q2 错、巩固错，其后全对 → 4/5
        for _ in range(3):
            r = await mp.submit_answer(conn, str(mp.store.get(conn.device_id)["questions"][mp.store.get(conn.device_id)["idx"]]["answer"]))
            if mp.store.get(conn.device_id) is None:
                break
        assert "练习完成" in r.result and "答对4题，共5题" in r.result
        assert mp.store.get(conn.device_id) is None
        assert conn.device_id not in mp._timers

    async def test_reinforce_correct_returns_to_main(self):
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        await mp.submit_answer(conn, wrong_for(s["questions"][0]))
        await mp.submit_answer(conn, wrong_for(s["questions"][0]))
        reinforce = mp.store.get(conn.device_id)["questions"][1]
        r = await mp.submit_answer(conn, str(reinforce["answer"]))
        assert "巩固题也答对" in r.result
        s = mp.store.get(conn.device_id)
        assert s["questions"][s["idx"]]["role"] == "main" and s["idx"] == 2

    async def test_chinese_number_answer(self):
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        ans = s["questions"][0]["answer"]
        r = await mp.submit_answer(conn, generator.cn_int(ans))
        assert "答对" in r.result

    async def test_end_practice_deletes_session(self):
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        r = await mp.end_practice(conn)
        assert "已完成0/5" in r.result and "答对0题" in r.result
        assert mp.store.get(conn.device_id) is None
        r = await mp.end_practice(conn)
        assert "没有进行中" in r.result

    async def test_resume_and_restart(self):
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        await mp.submit_answer(conn, str(s["questions"][0]["answer"]))

        r = await mp.start_practice(conn, difficulty="一上")
        assert "继续上次的" in r.result and "重新开始" in r.result
        assert mp.store.get(conn.device_id)["idx"] == 1  # 未受影响

        r = await mp.start_practice(conn, difficulty="一上", mode="resume")
        assert "继续上次的练习" in r.result
        assert any(v.startswith("2/5") for v in stt_views(conn))

        r = await mp.start_practice(conn, difficulty="一年级下", mode="restart")
        s = mp.store.get(conn.device_id)
        assert s["idx"] == 0 and s["total"] == 5 and set(q["role"] for q in s["questions"]) == {"main"}

    async def test_unparsed_answer_keeps_question(self):
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        before = s["idx"]
        r = await mp.submit_answer(conn, "不知道")
        assert "没有解析出" in r.result
        assert mp.store.get(conn.device_id)["idx"] == before

    async def test_no_session_submit(self):
        conn = make_conn()
        r = await mp.submit_answer(conn, "5")
        assert "没有进行中" in r.result


class TestNudgeTimer:
    @pytest.fixture(autouse=True)
    def _need_real_sleep(self, _real_sleep):
        """见模块级 _real_sleep fixture。"""
        return None

    async def test_timeout_skips_and_advances(self):
        conn = make_conn(nudge=0.05, count=5)
        await mp.start_practice(conn, difficulty="一上")
        await asyncio.sleep(0.18)
        s = mp.store.get(conn.device_id)
        assert s is not None and s["idx"] >= 1  # 超时跳过第 1 题
        assert any("正确答案" in t for t in conn.tts.stored)

    async def test_end_practice_cancels_timer(self):
        conn = make_conn(nudge=0.05, count=5)
        await mp.start_practice(conn, difficulty="一上")
        await mp.end_practice(conn)
        await asyncio.sleep(0.18)
        assert conn.tts.stored == []
        assert mp.store.get(conn.device_id) is None

    async def test_timeout_chain_stops_after_two_skips(self):
        """连续两次超时跳过后停超时链，保留会话供 resume（不自动跑完上报失真记录）。"""
        conn = make_conn(nudge=0.05, count=5)
        await mp.start_practice(conn, difficulty="一上")
        await asyncio.sleep(0.5)  # 足够跳过 ≥2 题
        s = mp.store.get(conn.device_id)
        assert s is not None and s["timeout_skips"] >= 2  # 会话保留未跑完
        assert any("休息一下" in t for t in conn.tts.stored)
        assert conn.device_id not in mp._timers  # 链已停


class TestDeviceConfigAndReport:
    """切片②：设备级配置（admin 配置页）与练习记录上报。"""

    async def test_device_config_overrides(self, monkeypatch):
        async def fake_fetch(conn):
            return {"preset": "g2a", "typeIds": ["M1", "M2"], "questionCount": 5}

        monkeypatch.setattr(mp, "_fetch_device_config", fake_fetch)
        conn = make_conn(count=5)
        conn.config["read_config_from_api"] = True
        await mp.start_practice(conn, difficulty="一上")  # 远端配置优先于 difficulty
        s = mp.store.get(conn.device_id)
        assert s["preset"] == "g2a" and s["total"] == 5
        assert {q["type"] for q in s["questions"]} <= {"M1", "M2"}

    async def test_fetch_failure_falls_back(self, monkeypatch):
        async def failing_fetch(conn):
            raise RuntimeError("api down")

        monkeypatch.setattr(mp, "_fetch_device_config", failing_fetch)
        conn = make_conn(count=5)
        conn.config["read_config_from_api"] = True
        await mp.start_practice(conn, difficulty="一年级下")  # 回落 difficulty + config.yaml
        s = mp.store.get(conn.device_id)
        assert s["preset"] == "g1b" and s["total"] == 5
        assert {q["type"] for q in s["questions"]} <= set(generator.PRESETS["g1b"])

    async def test_invalid_remote_fields_ignored(self, monkeypatch):
        async def fake_fetch(conn):
            return {"preset": "g9x", "typeIds": ["A1", "BAD"], "questionCount": 99}

        monkeypatch.setattr(mp, "_fetch_device_config", fake_fetch)
        conn = make_conn(count=5)
        conn.config["read_config_from_api"] = True
        await mp.start_practice(conn, difficulty="")
        s = mp.store.get(conn.device_id)
        # 非法预设回落 g1a；BAD 被滤掉只剩 A1（小题库），99 钳 20 后 total 对齐实际题数
        assert s["preset"] == "g1a"
        assert {q["type"] for q in s["questions"]} == {"A1"}
        assert s["total"] == len(s["questions"]) < 20

    async def test_no_api_mode_never_fetches(self, monkeypatch):
        called = []

        async def fake_fetch(conn):
            called.append(1)
            return {"preset": "g2a"}

        monkeypatch.setattr(mp, "_fetch_device_config", fake_fetch)
        conn = make_conn(count=5)  # 未开 read_config_from_api
        await mp.start_practice(conn, difficulty="一上")
        assert called == []
        assert mp.store.get(conn.device_id)["preset"] == "g1a"

    async def test_report_on_complete(self, monkeypatch):
        reported = []

        async def fake_report(conn, s):
            reported.append(s)

        monkeypatch.setattr(mp, "_report_result", fake_report)
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        for qq in mp.store.get(conn.device_id)["questions"]:
            await mp.submit_answer(conn, str(qq["answer"]))
        if mp._report_tasks:  # 等 fire-and-forget 上报落地
            await asyncio.wait_for(asyncio.gather(*list(mp._report_tasks)), timeout=1)
        assert len(reported) == 1
        s = reported[0]
        assert s["preset"] == "g1a" and s["total"] == 5 and s["score"] == 5
        assert "started_at" in s  # 时长由此计算

    async def test_report_on_end_practice(self, monkeypatch):
        reported = []

        async def fake_report(conn, s):
            reported.append(s)

        monkeypatch.setattr(mp, "_report_result", fake_report)
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        await mp.end_practice(conn)
        if mp._report_tasks:
            await asyncio.wait_for(asyncio.gather(*list(mp._report_tasks)), timeout=1)
        assert len(reported) == 1 and reported[0]["total"] == 5

    async def test_small_pool_total_clamped(self, monkeypatch):
        """单题型 A1 去重后仅 12 题：total 须对齐实际题数，防收尾前越界。"""
        async def fake_fetch(conn):
            return {"preset": "preschool", "typeIds": ["A1"], "questionCount": 20}

        monkeypatch.setattr(mp, "_fetch_device_config", fake_fetch)
        conn = make_conn()
        conn.config["read_config_from_api"] = True
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        assert s["total"] == len(s["questions"]) <= 12
        for qq in s["questions"]:  # 全程答完不越界
            await mp.submit_answer(conn, str(qq["answer"]))
        assert mp.store.get(conn.device_id) is None

    async def test_answer_resets_timeout_skips(self):
        conn = make_conn(nudge=0.05, count=5)
        await mp.start_practice(conn, difficulty="一上")
        mp.store.save({**mp.store.get(conn.device_id), "timeout_skips": 2})
        s = mp.store.get(conn.device_id)
        await mp.submit_answer(conn, str(s["questions"][s["idx"]]["answer"]))
        assert mp.store.get(conn.device_id)["timeout_skips"] == 0


# ───────────────────────── streak（#29：P2 学习进度屏） ─────────────────────────

class TestStreak:
    """单计数器口径：主题答对 +1、判错清零、巩固题不计、超时清零、跨会话续接。"""

    async def test_correct_increments_first_wrong_holds_second_wrong_resets(self):
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        await mp.submit_answer(conn, str(s["questions"][0]["answer"]))
        assert mp.store.get(conn.device_id)["streak"] == 1

        q2 = mp.store.get(conn.device_id)["questions"][1]
        await mp.submit_answer(conn, wrong_for(q2))  # 首错：未判决，streak 不动
        assert mp.store.get(conn.device_id)["streak"] == 1
        await mp.submit_answer(conn, wrong_for(q2))  # 二错：判错清零
        s = mp.store.get(conn.device_id)
        assert s["streak"] == 0 and s["streak_peak"] == 1

    async def test_retry_correct_counts(self):
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        q = s["questions"][0]
        await mp.submit_answer(conn, wrong_for(q))
        await mp.submit_answer(conn, str(q["answer"]))  # 重试答对 = 判对
        assert mp.store.get(conn.device_id)["streak"] == 1

    async def test_reinforce_not_counted(self, monkeypatch):
        """巩固题对不 +1、错不清零（#26：学习环节非考核）——用续接底数做判别。"""
        async def fake_fetch(conn):
            return {"streakEnd": 2}

        monkeypatch.setattr(mp, "_fetch_device_config", fake_fetch)
        conn = make_conn(count=5)
        conn.config["read_config_from_api"] = True
        await mp.start_practice(conn, difficulty="一上")
        q = mp.store.get(conn.device_id)["questions"][0]
        await mp.submit_answer(conn, wrong_for(q))
        await mp.submit_answer(conn, wrong_for(q))  # 二错：判错清零（2→0），插巩固题
        assert mp.store.get(conn.device_id)["streak"] == 0
        reinforce = mp.store.get(conn.device_id)["questions"][mp.store.get(conn.device_id)["idx"]]
        await mp.submit_answer(conn, str(reinforce["answer"]))  # 巩固题对：不 +1
        s = mp.store.get(conn.device_id)
        assert s["streak"] == 0 and s["streak_peak"] == 2  # 底数 2 已随清零丢失，峰值保留

    async def test_peak_survives_reset(self):
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        await mp.submit_answer(conn, str(s["questions"][0]["answer"]))
        await mp.submit_answer(conn, str(mp.store.get(conn.device_id)["questions"][1]["answer"]))
        await mp.submit_answer(conn, str(mp.store.get(conn.device_id)["questions"][2]["answer"]))
        assert mp.store.get(conn.device_id)["streak_peak"] == 3
        q = mp.store.get(conn.device_id)["questions"][3]
        await mp.submit_answer(conn, wrong_for(q))
        await mp.submit_answer(conn, wrong_for(q))
        s = mp.store.get(conn.device_id)
        assert s["streak"] == 0 and s["streak_peak"] == 3  # 峰值不清
        await mp.submit_answer(conn, str(s["questions"][s["idx"]]["answer"]))  # 巩固题对：不计
        r = await mp.submit_answer(conn, str(mp.store.get(conn.device_id)["questions"][mp.store.get(conn.device_id)["idx"]]["answer"]))  # 第5主题对 → 收尾
        assert "答对4题" in r.result  # q1-q3 + q5
        assert mp._last_streak_end.get(conn.device_id) == 1  # 清零后重新攒到 1
        assert mp.store.get(conn.device_id) is None

    async def test_timeout_skip_clears_streak(self, _real_sleep):
        conn = make_conn(nudge=0.05, count=5)
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        await mp.submit_answer(conn, str(s["questions"][0]["answer"]))  # streak 1
        await asyncio.sleep(0.18)  # 第 2 题超时跳过（跳过=不会，清零）
        assert mp.store.get(conn.device_id)["streak"] == 0

    async def test_continues_from_remote_streak_end(self, monkeypatch):
        async def fake_fetch(conn):
            return {"streakEnd": 3}

        monkeypatch.setattr(mp, "_fetch_device_config", fake_fetch)
        conn = make_conn(count=5)
        conn.config["read_config_from_api"] = True
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        assert s["streak"] == 3 and s["streak_peak"] == 3  # 峰值含续接底数
        await mp.submit_answer(conn, str(s["questions"][0]["answer"]))
        assert mp.store.get(conn.device_id)["streak"] == 4

    async def test_continues_in_process_after_report(self, monkeypatch):
        """连玩两轮：上一轮收尾上报后进程内即记 streak_end，新轮免等落库即续接。"""
        async def fake_report(conn, s):
            pass

        monkeypatch.setattr(mp, "_report_result", fake_report)
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        for qq in list(mp.store.get(conn.device_id)["questions"]):
            await mp.submit_answer(conn, str(qq["answer"]))
        assert mp._last_streak_end.get(conn.device_id) == 5
        await mp.start_practice(conn, difficulty="一上")  # 新一轮
        assert mp.store.get(conn.device_id)["streak"] == 5

    async def test_report_carries_streak_values(self, monkeypatch):
        captured = {}

        async def fake_report(mac, preset, total, correct, duration, streak_end, streak_peak):
            captured.update(streak_end=streak_end, streak_peak=streak_peak)

        monkeypatch.setattr("config.manage_api_client.report_math_practice", fake_report)
        conn = make_conn(count=5)
        await mp.start_practice(conn, difficulty="一上")
        q1 = mp.store.get(conn.device_id)["questions"][0]
        await mp.submit_answer(conn, str(q1["answer"]))
        q2 = mp.store.get(conn.device_id)["questions"][1]
        await mp.submit_answer(conn, wrong_for(q2))
        await mp.submit_answer(conn, wrong_for(q2))
        await mp.end_practice(conn)  # 中途退出：streak 0、peak 1 随记录上报
        if mp._report_tasks:
            await asyncio.wait_for(asyncio.gather(*list(mp._report_tasks)), timeout=1)
        assert captured == {"streak_end": 0, "streak_peak": 1}


# ───────────────────────── 进度推送（#29：update_progress 主通道） ─────────────────────────

AGG = {
    "todayCorrect": 7, "todayTotal": 10, "todayMaxStreak": 4,
    "currentStreak": 2, "bestStreak": 9,
    "weekAccuracy": 70, "weekCorrect": 14, "weekTotal": 20,
    "recentSessions": [{"time": "2026-10-25 20:00", "correct": 7, "total": 10, "streakPeak": 4}],
}


def progress_pushes(conn):
    return [m["payload"]["params"] for m in conn.sent
            if m.get("type") == "mcp" and m["payload"].get("method") == "tools/call"]


async def drain_tasks():
    if mp._report_tasks:
        await asyncio.wait_for(asyncio.gather(*list(mp._report_tasks)), timeout=2)


class TestProgressPush:
    """推送时机（判决推进后/收尾/停链）+ 全量 8 字段 + 会话实时值叠加。"""

    async def test_push_after_correct_judgment_overlays_live_session(self, monkeypatch):
        async def fake_progress(mac, token):
            assert token == "tk"
            return dict(AGG)

        monkeypatch.setattr("config.manage_api_client.get_math_practice_progress", fake_progress)
        conn = make_conn(count=5, token="tk", mcp=FakeMCPClient())
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        await mp.submit_answer(conn, str(s["questions"][0]["answer"]))
        await drain_tasks()
        pushes = progress_pushes(conn)
        assert len(pushes) == 1
        assert pushes[0]["name"] == "update_progress"
        a = pushes[0]["arguments"]
        assert a["todayCorrect"] == 8 and a["todayTotal"] == 11  # 聚合 + 本会话
        assert a["currentStreak"] == 1 and a["todayMaxStreak"] == 4 and a["bestStreak"] == 9
        assert a["weekAccuracy"] == 71  # (14+1)/(20+1) = 71.4% → 71
        assert a["recentSessions"][0] == {  # 进行中会话插到最近场次之首
            "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(s["started_at"])),
            "correct": 1, "total": 1, "streakPeak": 1,
        }

    async def test_no_push_before_judgment_or_without_channel(self, monkeypatch):
        async def fake_progress(mac, token):
            return dict(AGG)

        monkeypatch.setattr("config.manage_api_client.get_math_practice_progress", fake_progress)
        conn = make_conn(count=5, token="tk", mcp=FakeMCPClient())
        await mp.start_practice(conn, difficulty="一上")
        s = mp.store.get(conn.device_id)
        await mp.submit_answer(conn, "不知道")  # 未解析：不推
        q = s["questions"][0]
        await mp.submit_answer(conn, wrong_for(q))  # 首错未判决：不推
        await drain_tasks()
        assert progress_pushes(conn) == []

        conn2 = make_conn(count=5, token="", mcp=FakeMCPClient())  # 未配 token：整体关闭
        await mp.start_practice(conn2, difficulty="一上")
        await mp.submit_answer(conn2, str(mp.store.get(conn2.device_id)["questions"][0]["answer"]))
        await drain_tasks()
        assert progress_pushes(conn2) == []

        conn3 = make_conn(count=5, token="tk")  # 设备未注册 MCP 工具：静默跳过
        await mp.start_practice(conn3, difficulty="一上")
        await mp.submit_answer(conn3, str(mp.store.get(conn3.device_id)["questions"][0]["answer"]))
        await drain_tasks()
        assert progress_pushes(conn3) == []

        conn4 = make_conn(count=5, token="tk", mcp=FakeMCPClient(tools=()))  # 无 update_progress
        await mp.start_practice(conn4, difficulty="一上")
        await mp.submit_answer(conn4, str(mp.store.get(conn4.device_id)["questions"][0]["answer"]))
        await drain_tasks()
        assert progress_pushes(conn4) == []

    async def test_wrap_up_pushes_pure_aggregate_after_report(self, monkeypatch):
        async def fake_progress(mac, token):
            return dict(AGG)

        monkeypatch.setattr("config.manage_api_client.get_math_practice_progress", fake_progress)
        conn = make_conn(count=5, token="tk", mcp=FakeMCPClient())
        await mp.start_practice(conn, difficulty="一上")
        for qq in list(mp.store.get(conn.device_id)["questions"]):
            await mp.submit_answer(conn, str(qq["answer"]))
        await drain_tasks()
        pushes = progress_pushes(conn)
        assert pushes  # 全程 4 次判决推进 + 收尾各一推
        assert pushes[-1]["arguments"] == AGG  # 收尾推纯聚合（record 落库后的口径）

    async def test_slow_report_holds_lock_against_new_round_push(self, monkeypatch, _real_sleep):
        """收尾上报整体持锁：慢上报期间新一轮的判决推送只能排其后，收尾推送
        不会被后判决先落屏再顶回旧聚合（#29 评审发现的回退竞态）。"""
        async def slow_report(conn, s):
            await asyncio.sleep(0.2)  # _real_sleep 已替换为真等待

        async def fake_progress(mac, token):
            return dict(AGG)

        monkeypatch.setattr(mp, "_report_result", slow_report)
        monkeypatch.setattr("config.manage_api_client.get_math_practice_progress", fake_progress)
        conn = make_conn(count=5, token="tk", mcp=FakeMCPClient())
        await mp.start_practice(conn, difficulty="一上")
        for qq in list(mp.store.get(conn.device_id)["questions"]):
            await mp.submit_answer(conn, str(qq["answer"]))  # 收尾：慢上报持锁中
        await mp.start_practice(conn, difficulty="一上")  # 立即开新一轮（进程内续接 seed=5）
        await mp.submit_answer(conn, str(mp.store.get(conn.device_id)["questions"][0]["answer"]))
        await drain_tasks()
        last = progress_pushes(conn)[-1]["arguments"]
        assert last["currentStreak"] == 6  # 新一轮实时值最后落屏，未被旧聚合顶回

    async def test_timeout_skip_and_chain_stop_push(self, monkeypatch, _real_sleep):
        async def fake_progress(mac, token):
            return dict(AGG)

        monkeypatch.setattr("config.manage_api_client.get_math_practice_progress", fake_progress)
        conn = make_conn(nudge=0.05, count=5, token="tk", mcp=FakeMCPClient())
        await mp.start_practice(conn, difficulty="一上")
        await asyncio.sleep(0.5)  # 连续两次超时跳过 → 停链（会话保留供 resume）
        await drain_tasks()
        args = [p["arguments"] for p in progress_pushes(conn)]
        assert args and all(a["currentStreak"] == 0 for a in args)  # 超时清零后的推送

