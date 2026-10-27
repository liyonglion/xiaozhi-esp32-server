"""答错讲解素材（#26 决议）：数字事实全部由代码计算，LLM 只负责组织语言。

方法库来自 #21 教学法调研：凑十法（看大数拆小数）、破十法、想乘算除、
乘法口诀、比大小「开口朝大数」、数的顺序 ±1、等差规律、数的组成。
"""
from __future__ import annotations

from .generator import cn_int


def _carry_add(a: int, b: int, ans: int) -> dict:
    """凑十法：个位相加满十。按数值取大数（47+8 应看大数 47、拆 8，
    而非按个位把 8 当大数）；进位条件 a%10+b%10>=10 保证 small >= take。"""
    big, small = (a, b) if a >= b else (b, a)
    take = 10 - big % 10
    if small == take:
        steps = f"{big}加{small}正好凑成{big + take}"
    else:
        steps = (
            f"看大数{big}，把{small}拆成{take}和{small - take}："
            f"{big}+{take}={big + take}，再{big + take}+{small - take}={ans}"
        )
    return {"method": "凑十法", "steps": steps}


def _borrow_sub(a: int, b: int, ans: int) -> dict:
    """破十法/借位减：个位不够减。"""
    ao, bo = a % 10, b % 10
    if a < 20:
        steps = f"个位{ao}不够减{bo}，先用10-{bo}={10 - bo}，再{10 - bo}+{ao}={ans}"
        return {"method": "破十法", "steps": steps}
    tens = a // 10 - 1 - b // 10
    ones = ao + 10 - bo
    steps = (
        f"个位{ao}不够减{bo}，向十位借一当十：{ao}+10={ao + 10}，"
        f"{ao + 10}-{bo}={ones}；十位{a // 10}借走1剩{a // 10 - 1}，"
        f"{a // 10 - 1}-{b // 10}={tens}，合起来是{ans}"
    )
    return {"method": "借位减法", "steps": steps}


def _mult_table(a: int, b: int) -> dict:
    """乘法口诀：小数在前（小九九）。"""
    small, big = sorted((a, b))
    prod = small * big
    koujue = f"{cn_int(small)}{cn_int(big)}{'得' if prod < 10 else ''}{cn_int(prod)}"
    return {"method": "乘法口诀", "steps": f"想口诀：{koujue}，所以{a}×{b}={prod}"}


def build_material(item: dict) -> dict:
    """一道题 → 讲解素材 {question, answer, method, steps}。"""
    m, ans, tid = item["meta"], item["answer"], item["type"]
    base = {"question": item["text"], "answer": ans}
    if tid.startswith("CMP"):
        x, y = m["x"], m["y"]
        if ans == "=":
            return base | {"method": "比大小", "steps": f"{x}和{y}一样大，所以填等于"}
        bigger = x if ans == ">" else y
        return base | {"method": "比大小", "steps": f"开口朝大数：{x}和{y}里{bigger}大，所以填{ans}"}
    if tid.startswith("ADJ"):
        x = m["x"]
        if m["side"] == "back":
            return base | {"method": "数的顺序", "steps": f"往后数就是加1：{x}+1={ans}"}
        return base | {"method": "数的顺序", "steps": f"往前数就是减1：{x}-1={ans}"}
    if tid.startswith("PAT"):
        if m["mode"] == "arith":
            d = m["seq"][1] - m["seq"][0]
            prev = m["seq"][3]
            return base | {"method": "找规律", "steps": f"每相邻两个数都相差{d}：{prev}+{d}={ans}"}
        a, b = m["seq"][0], m["seq"][1]
        return base | {"method": "找规律", "steps": f"规律是{a}和{b}交替出现，所以接着是{ans}"}
    if tid == "DEC":
        if m["ask"] == "part":
            return base | {"method": "数的组成", "steps": f"{m['n']}分成{m['p']}和{ans}：{m['p']}+{ans}={m['n']}"}
        return base | {"method": "数的组成", "steps": f"{m['p']}和{m['q']}合起来：{m['p']}+{m['q']}={ans}"}
    if tid == "M3":
        return base | {"method": "想口诀", "steps": f"几乘{m['a']}等于{m['prod']}？{ans}×{m['a']}={m['prod']}"}
    if tid[0] == "M":
        return base | _mult_table(m["a"], m["b"])
    if tid[0] == "D":
        d, dvd = m["d"], m["dividend"]
        return base | {"method": "想乘算除", "steps": f"想乘法：{ans}×{d}={dvd}，所以{dvd}÷{d}={ans}"}
    if tid[0] == "A":
        a, b = m["a"], m["b"]
        if a % 10 + b % 10 >= 10:
            return base | _carry_add(a, b, ans)
        return base | {"method": "验算", "steps": f"{a}+{b}={ans}，验算：{ans}-{b}={a}"}
    if tid[0] == "S":
        a, b = m["a"], m["b"]
        if a % 10 < b % 10:
            return base | _borrow_sub(a, b, ans)
        return base | {"method": "验算", "steps": f"{a}-{b}={ans}，验算：{ans}+{b}={a}"}
    raise ValueError(f"未知题型: {tid}")
