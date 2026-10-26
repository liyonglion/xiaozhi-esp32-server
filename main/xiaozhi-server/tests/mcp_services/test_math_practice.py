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
        self._conn.sent.append(json.loads(message))


def make_conn(device_id="AA:BB:CC:DD:EE:FF", nudge=0, count=5):
    conn = SimpleNamespace(
        device_id=device_id,
        config={"plugins": {"math_practice": {"count": count, "nudge_seconds": nudge}}},
        session_id="s1", sentence_id=1, intent_type="function_call",
        sent=[], logger=logger,
    )
    conn.tts = FakeTTS()
    conn.websocket = FakeWS(conn)
    return conn


def stt_views(conn):
    return [m["text"] for m in conn.sent if m.get("type") == "stt"]


def wrong_for(q):
    if q["kind"] == "int":
        return str(q["answer"] + 1) if q["answer"] < 100 else "99"
    return "大于号" if q["answer"] != ">" else "小于号"


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
    def _real_sleep(self, monkeypatch):
        """顶层 conftest 把 asyncio.sleep 换成了不 yield 的空操作（提速重试循环），
        计时器测试需要真实等待：用 executor 实现的真 sleep 替换回来。"""

        async def _real_sleep(seconds):
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, time.sleep, min(seconds, 0.3))

        monkeypatch.setattr(asyncio, "sleep", _real_sleep)

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
        assert s["preset"] == "g1a" and s["total"] == 20  # 非法预设回落，99 钳到 20
        assert "BAD" not in {q["type"] for q in s["questions"]}

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

