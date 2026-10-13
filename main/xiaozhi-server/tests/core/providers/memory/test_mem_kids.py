"""儿童长期记忆 provider（mem_kids，工单 #7）测试。

被测行为：本地摘要式记忆对齐小布（源工程）L3/L4 规则——
- 长期记忆为条目列表（{id, ts, text}），≤100 条，按 ts 升序注入 <memory>
- 记忆抽取走 LLM（连接上为 conn.slm）输出 JSON add/delete 操作，
  住址/证件号/电话号码硬排除
- 每 20 轮窗口压缩：旧摘要+近窗 → ≤300 字三要素滚动摘要
- 家长页能力：list_memories / delete_memory / clear_memory

外部边界：provider 公共接口（save_memory / query_memory / on_turn_end /
get_rolling_summary / list_memories / delete_memory / clear_memory）与
data/.memory_kids.yaml 持久化文件。LLM 一律 fake（response_no_stream），
不触网。先例：tests/test_memory.py、tests/core/test_connection_slm.py。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import yaml

from core.providers.memory.mem_kids.mem_kids import (
    COMPACT_INSTR,
    COMPACT_TURNS,
    EXTRACT_INSTR,
    MEM_MAX,
    SUMMARY_MAX,
    MemoryProvider,
)


class FakeSLM:
    """按 core/providers/llm/base.py 契约记录调用并回放脚本响应。"""

    def __init__(self, responses):
        self.calls = []  # [(system_prompt, user_prompt), ...]
        self._responses = list(responses)

    def response_no_stream(self, system_prompt, user_prompt, **kwargs):
        self.calls.append((system_prompt, user_prompt))
        item = self._responses.pop(0)
        return item(system_prompt, user_prompt) if callable(item) else item


def _make_provider(tmp_path, slm=None, role_id=None):
    p = MemoryProvider({}, None)
    p.memory_path = str(tmp_path / ".memory_kids.yaml")
    p.init_memory(
        role_id=role_id or f"kid-{uuid.uuid4().hex}", llm=slm, save_to_file=True
    )
    return p


def _seed_file(tmp_path, role_id, entries, summary=""):
    path = tmp_path / ".memory_kids.yaml"
    path.write_text(
        yaml.safe_dump({role_id: {"entries": entries, "summary": summary}},
                       allow_unicode=True),
        encoding="utf-8",
    )
    return str(path)


def test_query_memory_empty_returns_empty_string(tmp_path):
    p = _make_provider(tmp_path)
    assert asyncio.run(p.query_memory("你好")) == ""


def test_query_memory_renders_entries_in_ts_order(tmp_path):
    """L3 注入串：【小智记住的事】格式 + ts 升序条目，id 不进 prompt。"""
    role = "kid-order"
    entries = [
        {"id": 2, "ts": 200, "text": "喜欢恐龙"},
        {"id": 1, "ts": 100, "text": "在上大班"},
    ]
    path = _seed_file(tmp_path, role, entries)
    p = MemoryProvider({}, None)
    p.memory_path = path
    p.init_memory(role_id=role, llm=None)

    out = asyncio.run(p.query_memory("你好"))

    assert out.startswith("【小智记住的事】")
    lines = out.splitlines()
    assert lines[1] == "- 在上大班"
    assert lines[2] == "- 喜欢恐龙"


def test_rolling_summary_renders_with_header(tmp_path):
    """L4 注入串：【前面聊过的】+ 摘要正文；无摘要时为空串。"""
    role = "kid-sum"
    path = _seed_file(tmp_path, role, [], summary="孩子喜欢恐龙，聊得开心。")
    p = MemoryProvider({}, None)
    p.memory_path = path
    p.init_memory(role_id=role, llm=None)

    assert p.get_rolling_summary() == "【前面聊过的】\n孩子喜欢恐龙，聊得开心。"

    empty = _make_provider(tmp_path)
    assert empty.get_rolling_summary() == ""


# ---- 记忆抽取（save_memory = 连接关闭触发）----


def _msg(role, content):
    from core.utils.dialogue import Message

    return Message(role=role, content=content)


def test_save_memory_applies_add_and_delete_ops(tmp_path):
    """冲突消解：删除旧条目（按 id）再新增；结果持久化到文件。"""
    role = "kid-extract"
    path = _seed_file(tmp_path, role, [{"id": 1, "ts": 100, "text": "喜欢奥特曼"}])
    slm = FakeSLM([
        json.dumps(
            [{"op": "delete", "id": 1}, {"op": "add", "text": "喜欢恐龙"}],
            ensure_ascii=False,
        )
    ])
    p = MemoryProvider({}, None)
    p.memory_path = path
    p.init_memory(role_id=role, llm=slm)

    asyncio.run(
        p.save_memory([_msg("user", "我现在喜欢恐龙了"), _msg("assistant", "好呀")])
    )

    assert [e["text"] for e in p.list_memories()] == ["喜欢恐龙"]
    # 持久化：重载后仍在
    p2 = MemoryProvider({}, None)
    p2.memory_path = path
    p2.init_memory(role_id=role, llm=None)
    assert [e["text"] for e in p2.list_memories()] == ["喜欢恐龙"]

    # 抽取输入含【对话记录】与【现有记忆】节（小布（源工程）build_extract_text 契约）
    _sys, user_prompt = slm.calls[0]
    assert "【对话记录】" in user_prompt
    assert "孩子：我现在喜欢恐龙了" in user_prompt
    assert "【现有记忆】" in user_prompt
    assert "1. 喜欢奥特曼" in user_prompt


def test_sensitive_facts_never_enter_long_term_memory(tmp_path):
    """硬排除：住址/证件号/电话号码不入长期记忆（本地兜底，不依赖指令）。"""
    p = _make_provider(tmp_path, slm=FakeSLM([
        json.dumps(
            [
                {"op": "add", "text": "家住幸福路12号3号楼"},
                {"op": "add", "text": "电话是13812345678"},
                {"op": "add", "text": "身份证110101201601011234"},
                {"op": "add", "text": "喜欢恐龙"},
            ],
            ensure_ascii=False,
        )
    ]))

    asyncio.run(p.save_memory([_msg("user", "我家住幸福路12号")]))

    texts = [e["text"] for e in p.list_memories()]
    assert texts == ["喜欢恐龙"]


def test_duplicate_and_overlong_adds_rejected(tmp_path):
    """同文去重；超 30 字的条目拒收。"""
    role = "kid-dup"
    path = _seed_file(tmp_path, role, [{"id": 1, "ts": 100, "text": "喜欢恐龙"}])
    slm = FakeSLM([
        json.dumps(
            [
                {"op": "add", "text": "喜欢恐龙"},
                {"op": "add", "text": "超长" + "长" * 30},
            ],
            ensure_ascii=False,
        )
    ])
    p = MemoryProvider({}, None)
    p.memory_path = path
    p.init_memory(role_id=role, llm=slm)

    asyncio.run(p.save_memory([_msg("user", "我还是喜欢恐龙")]))

    assert [e["text"] for e in p.list_memories()] == ["喜欢恐龙"]


def test_cap_100_holds_with_model_eviction_policy(tmp_path):
    """封顶 100：模型带淘汰（add+delete）时保持 100；只 add 不淘汰则拒新条目。"""
    role = "kid-cap"
    entries = [{"id": i + 1, "ts": i + 1, "text": f"事实{i}"} for i in range(MEM_MAX)]
    path = _seed_file(tmp_path, role, entries)
    msgs = [_msg("user", "我喜欢积木")]

    # 只 add：拒新条目，条数不动
    p = MemoryProvider({}, None)
    p.memory_path = path
    p.init_memory(role_id=role, llm=FakeSLM([json.dumps([{"op": "add", "text": "喜欢积木"}], ensure_ascii=False)]))
    asyncio.run(p.save_memory(msgs))
    assert len(p.list_memories()) == MEM_MAX
    assert "喜欢积木" not in [e["text"] for e in p.list_memories()]

    # add + delete：模型淘汰最不重要的旧条目，腾位给新条目
    p2 = MemoryProvider({}, None)
    p2.memory_path = path
    p2.init_memory(role_id=role, llm=FakeSLM([
        json.dumps(
            [{"op": "delete", "id": 1}, {"op": "add", "text": "喜欢积木"}],
            ensure_ascii=False,
        )
    ]))
    asyncio.run(p2.save_memory(msgs))
    texts = [e["text"] for e in p2.list_memories()]
    assert len(texts) == MEM_MAX
    assert "喜欢积木" in texts
    assert "事实0" not in texts


def test_new_entries_get_incrementing_id_and_monotonic_ts(tmp_path):
    p = _make_provider(tmp_path, slm=FakeSLM([
        json.dumps([{"op": "add", "text": "喜欢恐龙"}, {"op": "add", "text": "在上大班"}], ensure_ascii=False)
    ]))
    before = int(time.time() * 1000)

    asyncio.run(p.save_memory([_msg("user", "我喜欢恐龙，在上大班")]))

    entries = p.list_memories()
    assert [e["id"] for e in entries] == [1, 2]
    assert all(e["ts"] >= before for e in entries)
    assert entries[0]["ts"] < entries[1]["ts"]


def test_save_memory_without_llm_degrades_silently(tmp_path):
    """无 SLM：不抛异常、不动条目（退化走现有行为）。"""
    p = _make_provider(tmp_path, slm=None)
    asyncio.run(p.save_memory([_msg("user", "我喜欢恐龙")]))
    assert p.list_memories() == []


def test_reinit_resets_watermarks_for_new_connection(tmp_path):
    """共享实例再连接（init_memory）：新对话窗口从零起算，抽取照常触发。"""
    slm = FakeSLM([json.dumps([{"op": "add", "text": "喜欢恐龙"}], ensure_ascii=False)])
    p = _make_provider(tmp_path, slm=slm)
    # 模拟上一连接推进过的水位
    p._extracted_upto = 40
    p._compacted_upto = 40
    p._turn_count = COMPACT_TURNS - 1

    p.init_memory(role_id=p.role_id, llm=slm)  # 新连接重新初始化

    asyncio.run(p.save_memory([_msg("user", "我喜欢恐龙")]))
    assert [e["text"] for e in p.list_memories()] == ["喜欢恐龙"]


# ---- 家长页能力：逐条删除 / 全量清除 ----


def test_delete_memory_removes_single_entry_and_persists(tmp_path):
    role = "kid-del"
    path = _seed_file(
        tmp_path, role,
        [{"id": 1, "ts": 100, "text": "喜欢恐龙"}, {"id": 2, "ts": 200, "text": "在上大班"}],
    )
    p = MemoryProvider({}, None)
    p.memory_path = path
    p.init_memory(role_id=role, llm=None)

    assert p.delete_memory(1) is True
    assert p.delete_memory(999) is False
    assert [e["text"] for e in p.list_memories()] == ["在上大班"]

    p2 = MemoryProvider({}, None)
    p2.memory_path = path
    p2.init_memory(role_id=role, llm=None)
    assert [e["text"] for e in p2.list_memories()] == ["在上大班"]


def test_clear_memory_wipes_entries_and_summary(tmp_path):
    """全量清除是隐私边界：条目与滚动摘要一起清，且落盘。"""
    role = "kid-wipe"
    path = _seed_file(
        tmp_path, role,
        [{"id": 1, "ts": 100, "text": "喜欢恐龙"}],
        summary="孩子喜欢恐龙，聊得开心。",
    )
    p = MemoryProvider({}, None)
    p.memory_path = path
    p.init_memory(role_id=role, llm=None)

    p.clear_memory()

    assert asyncio.run(p.query_memory("你好")) == ""
    assert p.get_rolling_summary() == ""
    p2 = MemoryProvider({}, None)
    p2.memory_path = path
    p2.init_memory(role_id=role, llm=None)
    assert p2.list_memories() == []
    assert p2.get_rolling_summary() == ""


# ---- 回合收尾后台趟：20 轮抽取+窗口压缩 ----


def test_on_turn_end_compacts_every_20_turns(tmp_path):
    """满 20 轮触发一趟：先抽取（第 1 次调用）再压缩（第 2 次调用）。"""
    extract_ops = json.dumps([{"op": "add", "text": "喜欢恐龙"}], ensure_ascii=False)
    compact_out = "孩子喜欢恐龙，常聊恐龙话题，情绪开心。"
    slm = FakeSLM([extract_ops, compact_out])
    p = _make_provider(tmp_path, slm=slm)
    msgs = [_msg("user", "我喜欢恐龙"), _msg("assistant", "好呀")]

    for _ in range(COMPACT_TURNS - 1):
        p.on_turn_end(msgs)
    assert slm.calls == []

    p.on_turn_end(msgs)  # 第 20 轮触发
    assert len(slm.calls) == 2
    extract_sys, extract_user = slm.calls[0]
    assert extract_sys == EXTRACT_INSTR
    assert "孩子：我喜欢恐龙" in extract_user
    compact_sys, compact_user = slm.calls[1]
    assert compact_sys == COMPACT_INSTR
    assert "【对话记录】" in compact_user

    # 摘要就位，回合计数清零：再跑 19 轮不触发
    assert p.get_rolling_summary() == f"【前面聊过的】\n{compact_out}"
    for _ in range(COMPACT_TURNS - 1):
        p.on_turn_end(msgs)
    assert len(slm.calls) == 2


def test_compaction_input_carries_old_summary_and_caps_output(tmp_path):
    """压缩输入带【旧摘要】；输出超 300 字时本地截断到 300。"""
    role = "kid-compact"
    path = _seed_file(tmp_path, role, [], summary="旧摘要：孩子爱恐龙。")
    slm = FakeSLM(["[]", "很长" * 300])  # 抽取空操作；压缩输出 600 字，超限
    p = MemoryProvider({}, None)
    p.memory_path = path
    p.init_memory(role_id=role, llm=slm)
    p._turn_count = COMPACT_TURNS - 1

    p.on_turn_end([_msg("user", "你好")])

    _sys, user_prompt = slm.calls[1]  # 第 2 次调用是压缩
    assert "【旧摘要】\n旧摘要：孩子爱恐龙。" in user_prompt
    assert len(p.summary) == SUMMARY_MAX


def test_compaction_failure_keeps_state_for_retry(tmp_path):
    """压缩失败：摘要/回合计数不动，条件仍满足下轮自然重试。"""
    slm = FakeSLM([
        "[]",  # 第 20 轮：抽取成功（空操作），水位推进
        RuntimeError("slm down"),  # 压缩炸了，摘要/计数不动
        "重试后的摘要",  # 下轮重试：抽取空窗跳过，压缩成功
    ])
    p = _make_provider(tmp_path, slm=slm)
    msgs = [_msg("user", "你好"), _msg("assistant", "嗯嗯")]

    p._turn_count = COMPACT_TURNS - 1
    p.on_turn_end(msgs)  # 抽取成功、压缩失败

    assert p.get_rolling_summary() == ""
    assert p._turn_count == COMPACT_TURNS  # 未清零

    p.on_turn_end(msgs)  # 计数仍满足：重试
    assert p.get_rolling_summary() == "【前面聊过的】\n重试后的摘要"
    assert len(slm.calls) == 3  # 抽取（空窗口跳过）+ 压缩重试成功


# ---- 家长页 HTTP 面底层操作（工单 #10）----


def _reset_registry(monkeypatch, tmp_path):
    """清实例登记并把文件 fallback 指到 tmp（隔离生产 .memory_kids.yaml）。"""
    import core.providers.memory.mem_kids.mem_kids as m

    m._INSTANCES.clear()
    monkeypatch.setattr(m, "_STORE_PATH", str(tmp_path / ".memory_kids.yaml"))


def test_parent_list_prefers_live_instance(tmp_path, monkeypatch):
    """有活跃实例（连接在）时走内存态：列表即时反映实例内条目。"""
    _reset_registry(monkeypatch, tmp_path)
    from core.providers.memory.mem_kids.mem_kids import list_for_role

    _seed_file(tmp_path, "kid-live", [{"id": 1, "ts": 100, "text": "喜欢恐龙"}])
    p = MemoryProvider({}, None)
    p.memory_path = str(tmp_path / ".memory_kids.yaml")
    p.init_memory(role_id="kid-live", llm=None)  # 登记 _INSTANCES

    assert list_for_role() == [{"id": 1, "ts": 100, "text": "喜欢恐龙"}]


def test_parent_list_falls_back_to_file_without_live_instance(tmp_path, monkeypatch):
    """无活跃实例（服务重启后无连接）时直接读文件，不谎报为空。"""
    _reset_registry(monkeypatch, tmp_path)
    from core.providers.memory.mem_kids.mem_kids import list_for_role

    _seed_file(tmp_path, "kid-file", [{"id": 3, "ts": 300, "text": "在上大班"}])

    assert list_for_role() == [{"id": 3, "ts": 300, "text": "在上大班"}]


def test_parent_delete_via_live_instance_persists(tmp_path, monkeypatch):
    """逐条删除经活跃实例：实例内存态与文件一致更新。"""
    _reset_registry(monkeypatch, tmp_path)
    from core.providers.memory.mem_kids.mem_kids import delete_for_role

    _seed_file(
        tmp_path,
        "kid-del",
        [
            {"id": 1, "ts": 100, "text": "喜欢恐龙"},
            {"id": 2, "ts": 200, "text": "在上大班"},
        ],
    )
    p = MemoryProvider({}, None)
    p.memory_path = str(tmp_path / ".memory_kids.yaml")
    p.init_memory(role_id="kid-del", llm=None)

    assert delete_for_role(1) is True
    assert [e["id"] for e in p.list_memories()] == [2]
    # 文件同步：重开实例仍在
    p2 = MemoryProvider({}, None)
    p2.memory_path = str(tmp_path / ".memory_kids.yaml")
    p2.init_memory(role_id="kid-del", llm=None)
    assert [e["id"] for e in p2.list_memories()] == [2]

    assert delete_for_role(99) is False


def test_parent_delete_falls_back_to_file(tmp_path, monkeypatch):
    """无活跃实例时直接改文件。"""
    _reset_registry(monkeypatch, tmp_path)
    from core.providers.memory.mem_kids.mem_kids import delete_for_role
    from core.providers.memory.mem_kids.mem_kids import list_for_role

    _seed_file(tmp_path, "kid-delf", [{"id": 5, "ts": 500, "text": "喜欢积木"}])

    assert delete_for_role(5) is True
    assert list_for_role() == []


def test_parent_clear_removes_entries_and_summary(tmp_path, monkeypatch):
    """全量清除：条目与滚动摘要一起清（隐私边界）。"""
    _reset_registry(monkeypatch, tmp_path)
    from core.providers.memory.mem_kids.mem_kids import clear_for_role

    _seed_file(
        tmp_path,
        "kid-clear",
        [{"id": 1, "ts": 100, "text": "喜欢恐龙"}],
        summary="孩子喜欢恐龙。",
    )

    clear_for_role()
    data = yaml.safe_load((tmp_path / ".memory_kids.yaml").read_text(encoding="utf-8"))
    assert data["kid-clear"] == {"entries": [], "summary": ""}

