"""口算/数感出题器（自 research/math-generator 原型转正，逻辑经 200 题/型独立复检）。

设计要点（地图 #20/#21/#25 决议）：
- 逆推构造：减法先定差与减数、除法先定除数与商，天然非负/整除，零重试
- 答案类型全局仅两种：非负整数 0~100、比较符号（确定性判题前提）
- 交换律同题去重；含 0 算术题每套 ≤1 道
- 年级预设五档（#24 决议，g1a 不含 5 以内档——#25 R1）
"""
from __future__ import annotations

import random
from typing import Any, Callable

Rng = random.Random


def q(tid: str, text: str, answer: Any, kind: str, meta: dict) -> dict:
    return {"type": tid, "text": text, "answer": answer, "kind": kind, "meta": meta}


# ───────────────────────── 口算四则 ─────────────────────────


def gen_a(rng: Rng, a_hi: int, sum_hi: int, tid: str) -> dict:
    a = rng.randint(0, a_hi)
    b = rng.randint(0, sum_hi - a)
    return q(tid, f"{a}+{b}=", a + b, "int", {"a": a, "b": b})


def gen_a3(rng: Rng) -> dict:  # 20 以内不进位加：十几 + 一位数，个位和 < 10
    a = rng.randint(10, 19)
    b = rng.randint(0, 9 - a % 10)
    return q("A3", f"{a}+{b}=", a + b, "int", {"a": a, "b": b})


def gen_a4(rng: Rng) -> dict:  # 20 以内进位加：两一位数，和 ∈ [10,18]
    a = rng.randint(5, 9)
    b = rng.randint(10 - a, 9)
    return q("A4", f"{a}+{b}=", a + b, "int", {"a": a, "b": b})


def gen_a5(rng: Rng) -> dict:  # 50 以内加法（产品过渡档）
    a = rng.randint(11, 49)
    b = rng.randint(1, min(9, 50 - a))
    return q("A5", f"{a}+{b}=", a + b, "int", {"a": a, "b": b})


def gen_a6(rng: Rng) -> dict:  # 两位数 + 一位数，和 ≤ 100
    a = rng.randint(10, 99)
    b = rng.randint(1, min(9, 100 - a))
    return q("A6", f"{a}+{b}=", a + b, "int", {"a": a, "b": b})


def gen_a7(rng: Rng) -> dict:  # 两位数 + 两位数，和 ≤ 100
    b = rng.randint(10, 90)
    a = rng.randint(10, 100 - b)
    return q("A7", f"{a}+{b}=", a + b, "int", {"a": a, "b": b})


def gen_s(rng: Rng, sub_hi: int, tid: str) -> dict:  # 逆推：先定差与减数
    c = rng.randint(0, sub_hi)
    b = rng.randint(0, sub_hi - c)
    a = b + c
    return q(tid, f"{a}-{b}=", c, "int", {"a": a, "b": b})


def gen_s3(rng: Rng) -> dict:  # 20 以内不退位减：十几 − 一位数，个位够减
    a = rng.randint(11, 19)
    b = rng.randint(0, a % 10)
    return q("S3", f"{a}-{b}=", a - b, "int", {"a": a, "b": b})


def gen_s4(rng: Rng) -> dict:  # 20 以内退位减（难点）；a=19 无解（个位 9 永远够减）
    a = rng.randint(11, 18)
    b = rng.randint(a % 10 + 1, 9)
    return q("S4", f"{a}-{b}=", a - b, "int", {"a": a, "b": b})


def gen_s5(rng: Rng) -> dict:  # 50 以内减法（过渡档）
    b = rng.randint(1, 9)
    a = rng.randint(b + 1, 50)
    return q("S5", f"{a}-{b}=", a - b, "int", {"a": a, "b": b})


def gen_s6(rng: Rng) -> dict:  # 两位数 − 一位数
    b = rng.randint(1, 9)
    a = rng.randint(max(b + 1, 10), 99)
    return q("S6", f"{a}-{b}=", a - b, "int", {"a": a, "b": b})


def gen_s7(rng: Rng) -> dict:  # 两位数 − 整十数
    b = 10 * rng.randint(1, 9)
    a = rng.randint(b + 1, 99)
    return q("S7", f"{a}-{b}=", a - b, "int", {"a": a, "b": b})


def gen_s8(rng: Rng) -> dict:  # 两位数 − 两位数，被减数 ≤ 100
    b = rng.randint(10, 99)
    a = rng.randint(b + 1, 100)
    return q("S8", f"{a}-{b}=", a - b, "int", {"a": a, "b": b})


def gen_m(rng: Rng, hi: int, tid: str) -> dict:
    a = rng.randint(1, hi)
    b = rng.randint(1, hi)
    return q(tid, f"{a}×{b}=", a * b, "int", {"a": a, "b": b})


def gen_m3(rng: Rng) -> dict:  # 乘数未知：a×?=a*b
    a = rng.randint(2, 9)
    b = rng.randint(2, 9)
    return q("M3", f"{a}×?={a * b}", b, "int", {"a": a, "prod": a * b})


def gen_d(rng: Rng, d_hi: int, tid: str) -> dict:  # 逆推：先定除数(≥2)与商
    d = rng.randint(2, d_hi)
    v = rng.randint(1, 9)
    return q(tid, f"{d * v}÷{d}=", v, "int", {"dividend": d * v, "d": d})


# ───────────────────────── 数感四类（按范围参数化） ─────────────────────────


def make_cmp(r: int) -> Callable[[Rng], dict]:
    """比大小：>、<、= 三种答案均衡配比，随机左右防定势。"""

    def gen(rng: Rng) -> dict:
        target = rng.choice([">", "<", "="])
        if target == "=":
            x = y = rng.randint(0, r)
        else:
            y = rng.randint(0, r - 1)
            x = rng.randint(y + 1, r)  # x > y
            if target == "<":
                x, y = y, x
        ans = ">" if x > y else ("<" if x < y else "=")
        return q(f"CMP{r}", f"{x}○{y}", ans, "sym", {"x": x, "y": y})

    return gen


def make_adj(r: int) -> Callable[[Rng], dict]:
    """相邻数：只做单边问法（双边答案双值，违背唯一性约束）。"""

    def gen(rng: Rng) -> dict:
        side = rng.choice(["front", "back"])
        if side == "back":
            x = rng.randint(0, r - 1)
            return q(f"ADJ{r}", f"{x}的后面一个数是几？", x + 1, "int", {"x": x, "side": side})
        x = rng.randint(1, r)  # 排除 0 的前一个数（不存在）
        return q(f"ADJ{r}", f"{x}的前面一个数是几？", x - 1, "int", {"x": x, "side": side})

    return gen


def make_pat(r: int) -> Callable[[Rng], dict]:
    """找规律：唯一性硬约束——等差呈现 ≥3 个差值（4 已知项）、交替 ≥2 完整周期。"""

    def gen(rng: Rng) -> dict:
        if rng.random() < 0.6:  # 等差
            d = rng.choice([1, 2, 3])
            s = rng.randint(0, r - 4 * d)
            terms = [s + i * d for i in range(5)]
            return q(f"PAT{r}", "、".join(map(str, terms[:4])) + "、□", terms[4], "int",
                     {"seq": terms, "mode": "arith"})
        a = rng.randint(1, 9)  # 交替 ABAB：4 已知项 = 2 完整周期
        b = rng.randint(1, 9)
        while b == a:
            b = rng.randint(1, 9)
        return q(f"PAT{r}", f"{a}、{b}、{a}、{b}、□", a, "int", {"seq": [a, b, a, b, a], "mode": "alt"})

    return gen


def gen_dec(rng: Rng) -> dict:
    """分与合：只做填空式（开放式多解禁用）；总数=10 加权（凑十法前置）。"""
    if rng.random() < 0.5:  # 给部分求部分
        n = rng.choice(list(range(2, 10)) + [10] * 3)
        p = rng.randint(1, n - 1)  # 排除含 0 的分解
        return q("DEC", f"{n}可以分成{p}和几？", n - p, "int", {"n": n, "p": p, "ask": "part"})
    p = rng.randint(1, 9)  # 求总数
    qv = rng.randint(1, 10 - p)
    return q("DEC", f"{p}和{qv}组成几？", p + qv, "int", {"p": p, "q": qv, "ask": "total"})


# ───────────────────────── 题型注册表 ─────────────────────────

TYPES: dict[str, dict] = {
    t["id"]: t
    for t in [
        {"id": "A1", "name": "5以内加法", "kind": "int", "gen": lambda r: gen_a(r, 5, 5, "A1")},
        {"id": "A2", "name": "10以内加法", "kind": "int", "gen": lambda r: gen_a(r, 10, 10, "A2")},
        {"id": "A3", "name": "20以内不进位加", "kind": "int", "gen": gen_a3},
        {"id": "A4", "name": "20以内进位加", "kind": "int", "gen": gen_a4},
        {"id": "A5", "name": "50以内加法(过渡档)", "kind": "int", "gen": gen_a5},
        {"id": "A6", "name": "两位数+一位数", "kind": "int", "gen": gen_a6},
        {"id": "A7", "name": "两位数+两位数", "kind": "int", "gen": gen_a7},
        {"id": "S1", "name": "5以内减法", "kind": "int", "gen": lambda r: gen_s(r, 5, "S1")},
        {"id": "S2", "name": "10以内减法", "kind": "int", "gen": lambda r: gen_s(r, 10, "S2")},
        {"id": "S3", "name": "20以内不退位减", "kind": "int", "gen": gen_s3},
        {"id": "S4", "name": "20以内退位减(难点)", "kind": "int", "gen": gen_s4},
        {"id": "S5", "name": "50以内减法(过渡档)", "kind": "int", "gen": gen_s5},
        {"id": "S6", "name": "两位数-一位数", "kind": "int", "gen": gen_s6},
        {"id": "S7", "name": "两位数-整十数", "kind": "int", "gen": gen_s7},
        {"id": "S8", "name": "两位数-两位数", "kind": "int", "gen": gen_s8},
        {"id": "M1", "name": "表内乘法(口诀≤6)", "kind": "int", "gen": lambda r: gen_m(r, 6, "M1")},
        {"id": "M2", "name": "表内乘法(全口诀)", "kind": "int", "gen": lambda r: gen_m(r, 9, "M2")},
        {"id": "M3", "name": "乘数未知", "kind": "int", "gen": gen_m3},
        {"id": "D1", "name": "表内除法(口诀≤6)", "kind": "int", "gen": lambda r: gen_d(r, 6, "D1")},
        {"id": "D2", "name": "表内除法(全口诀)", "kind": "int", "gen": lambda r: gen_d(r, 9, "D2")},
        {"id": "CMP5", "name": "比大小(5以内)", "kind": "sym", "gen": make_cmp(5)},
        {"id": "CMP10", "name": "比大小(10以内)", "kind": "sym", "gen": make_cmp(10)},
        {"id": "CMP100", "name": "比大小(100以内)", "kind": "sym", "gen": make_cmp(100)},
        {"id": "ADJ100", "name": "相邻数(100以内)", "kind": "int", "gen": make_adj(100)},
        {"id": "PAT20", "name": "找规律(20以内)", "kind": "int", "gen": make_pat(20)},
        {"id": "DEC", "name": "分与合", "kind": "int", "gen": gen_dec},
    ]
}

# 年级预设（#24 决议；g1a 不含 5 以内档——#25 R1 决议）
PRESETS: dict[str, list[str]] = {
    "preschool": ["A1", "S1", "CMP5", "DEC", "PAT20"],
    "g1a": ["A2", "A3", "S2", "A4", "CMP10", "DEC"],
    "g1b": ["S3", "S4", "A5", "S5", "A6", "S7", "ADJ100"],
    "g2a": ["M1", "M2", "A7", "S8"],
    "g2b": ["D1", "D2", "M2", "M3", "A7", "S8"],
}

PRESET_NAMES = {
    "preschool": "学前",
    "g1a": "一年级上",
    "g1b": "一年级下",
    "g2a": "二年级上",
    "g2b": "二年级下",
}

# 未配置兜底（#24 决议：LLM 对话问年级；孩子答不上时的一上档）
FALLBACK_PRESET = "g1a"


def canonical_key(item: dict) -> tuple:
    """去重键：加减乘按交换律规范化（a+b ≡ b+a），其余按题面。"""
    m, tid = item["meta"], item["type"]
    if tid[0] in "ASM" and {"a", "b"} <= m.keys():
        return (tid, min(m["a"], m["b"]), max(m["a"], m["b"]))
    return (tid, item["text"])


def has_zero_operand(item: dict) -> bool:
    """算术题是否含 0 操作数（10-0= 教材合法但一套多道显得水）。"""
    m = item["meta"]
    return item["type"][0] in "AS" and 0 in (m.get("a", -1), m.get("b", -1))


def generate_practice(type_ids: list[str], count: int, rng: Rng) -> list[dict]:
    """按题型列表轮转出一套 count 题，交换律同题去重，含 0 算术题每套 ≤1 道。"""
    seen: set = set()
    zero_used = False
    out: list[dict] = []
    for i in range(count * 30):
        if len(out) >= count:
            break
        tid = type_ids[i % len(type_ids)]
        item = TYPES[tid]["gen"](rng)
        key = canonical_key(item)
        if key in seen:
            continue
        if has_zero_operand(item):
            if zero_used:
                continue
            zero_used = True
        seen.add(key)
        out.append(item)
    return out


# ───────────────────────── 答案归一化与判题 ─────────────────────────

_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_FROM_DIGIT = {v: k for k, v in _CN_DIGIT.items()}
_SYMBOLS = [
    (">", ("大于", "大于号", "＞")),
    ("<", ("小于", "小于号", "＜")),
    ("=", ("等于", "等于号", "一样", "相等", "相同", "＝")),
]


def _cn_to_int(s: str) -> int | None:
    """汉字数字 → 0~100 的整数；解析不了返回 None。"""
    if s == "一百":
        return 100
    if "十" in s:
        left, _, right = s.partition("十")
        if (left and left not in _CN_DIGIT) or (right and right not in _CN_DIGIT):
            return None
        tens = _CN_DIGIT[left] if left else 1
        ones = _CN_DIGIT[right] if right else 0
        return tens * 10 + ones
    return _CN_DIGIT.get(s)


def cn_int(n: int) -> str:
    """整数（0~100）→ 汉字（口诀、讲解文本用）。"""
    if n < 10:
        return _CN_FROM_DIGIT[n]
    if n == 10:
        return "十"
    if n == 100:
        return "一百"
    tens, ones = divmod(n, 10)
    head = "" if tens == 1 else _CN_FROM_DIGIT[tens]
    return head + "十" + (_CN_FROM_DIGIT[ones] if ones else "")


def normalize_answer(text: str, kind: str) -> int | str | None:
    """ASR 文本 → 标准答案类型；解析失败返回 None（调用方交 LLM 兜底解析）。"""
    t = text.strip().replace("两", "二")
    t = "".join(ch for ch in t if ch not in "。，！？. 、")
    if kind == "sym":
        for sym, words in _SYMBOLS:
            if t == sym or t in words:
                return sym
        return None
    if t.isdigit():
        n = int(t)
        return n if 0 <= n <= 100 else None
    return _cn_to_int(t)
