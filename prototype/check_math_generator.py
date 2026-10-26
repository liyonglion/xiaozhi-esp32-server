"""出题器原型自检 — PROTOTYPE（wayfinder #25）

每题型批量生成并独立复检约束（不超纲）+ 去重/归一化/预设/确定性断言。
运行：python3 prototype/check_math_generator.py
"""
from __future__ import annotations

import random

from math_generator import (
    FALLBACK_PRESET, PRESETS, TYPES, canonical_key, generate_practice,
    has_zero_operand, judge, normalize_answer,
)

N = 200  # 每题型抽检量（票要求 ≥10，加严到 200）


# 各题型独立复检：从 meta 重推约束与答案，不信任生成器自己的计算
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
for r in (5, 10, 100):
    CHECKS[f"CMP{r}"] = (lambda r: lambda m, ans: 0 <= m["x"] <= r and 0 <= m["y"] <= r
                         and ans == (">" if m["x"] > m["y"] else "<" if m["x"] < m["y"] else "="))(r)


def main() -> None:
    # 1) 每题型批量生成，独立复检约束 + 答案类型 + 题面长度（屏幕预算 ≤20 字符）
    for tid, t in TYPES.items():
        rng = random.Random(hash(tid) % 2**31)
        for _ in range(N):
            item = t["gen"](rng)
            assert CHECKS[tid](item["meta"], item["answer"]), f"{tid} 超纲/算错: {item}"
            assert item["kind"] == t["kind"]
            if item["kind"] == "int":
                assert isinstance(item["answer"], int) and 0 <= item["answer"] <= 100, f"{tid} 答案越界: {item}"
            else:
                assert item["answer"] in (">", "<", "="), f"{tid} 符号非法: {item}"
            assert len(item["text"]) <= 20, f"{tid} 题面超 20 字符: {item['text']}"
    # 比大小三符号都要出得到（均衡配比）
    seen_syms = {TYPES["CMP10"]["gen"](random.Random(i))["answer"] for i in range(60)}
    assert seen_syms == {">", "<", "="}, seen_syms

    # 2) 去重：交换律同题归一 + 整套无重复
    rng = random.Random(1)
    set_a = generate_practice(["A2"], 20, rng)
    assert len({canonical_key(i) for i in set_a}) == 20
    assert canonical_key({"type": "A2", "meta": {"a": 3, "b": 5}}) == canonical_key({"type": "A2", "meta": {"a": 5, "b": 3}})
    # 含 0 算术题每套 ≤1 道（R2 决议）
    zs = generate_practice(["A1", "S1"], 10, rng)
    assert len(zs) == 10 and sum(has_zero_operand(i) for i in zs) <= 1

    # 3) 答案归一化（ASR 口语 → 标准答案）
    cases_int = [("12", 12), ("十二", 12), ("一十二", 12), ("二十", 20), ("十五", 15),
                 ("一百", 100), ("零", 0), ("两", 2), ("10。", 10), ("一百零一", None), ("十二岁", None), ("abc", None)]
    for spoken, want in cases_int:
        assert normalize_answer(spoken, "int") == want, (spoken, normalize_answer(spoken, "int"))
    cases_sym = [("大于号", ">"), ("大于", ">"), ("＞", ">"), ("小于号", "<"), ("等于", "="), ("等于号", "="), ("一样", "="), ("相等", "="), ("差不多", None)]
    for spoken, want in cases_sym:
        assert normalize_answer(spoken, "sym") == want, (spoken, normalize_answer(spoken, "sym"))

    # 4) 判题：对/错/胡话三态
    q4 = {"type": "A4", "text": "8+9=", "answer": 17, "kind": "int", "meta": {"a": 8, "b": 9}}
    assert judge(q4, "十七") and judge(q4, "17") and not judge(q4, "18") and not judge(q4, "不知道")

    # 5) 预设：ID 全部存在、每档出满 10 题、兜底档有效
    for name, ids in PRESETS.items():
        assert all(i in TYPES for i in ids), name
        got = generate_practice(ids, 10, random.Random(7))
        assert len(got) == 10, name
    assert FALLBACK_PRESET in PRESETS

    # 6) 确定性：同种子同题序
    a = [i["text"] for i in generate_practice(PRESETS["g1a"], 5, random.Random(7))]
    b = [i["text"] for i in generate_practice(PRESETS["g1a"], 5, random.Random(7))]
    assert a == b

    print(f"OK：{len(TYPES)} 个题型 × {N} 抽检全过；去重/归一化/判题/预设/确定性全过")


if __name__ == "__main__":
    main()
