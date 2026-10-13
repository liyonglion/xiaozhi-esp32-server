"""孩子档案与年龄分档纯函数（工单 #6，L2 档案层）。

档案经 per-agent 下发通道（manager-api Agent.kidProfile JSON，下发键名
``kids``）或 config.yaml 顶层 ``kids`` 块（文件模式 fallback）到达
``self.config["kids"]``，两种模式共用同一读取代码。块形状::

    kids:
      enabled: true          # 儿童模式总开关（#5 消费同一布尔）
      nickname: 小豆          # 称呼（档案主字段）
      birth_ym: "2019-05"    # 出生年月 YYYY-MM（档案主字段）
      personality: ...       # 性格（可选）
      hobbies: ...           # 爱好（可选）
      instructions: ...      # 家长嘱托（可选）
      taboos: [.., ..]       # 个性化禁忌（可选，一行一条）

年龄按月粒度计算满岁（生日月即满岁，溯源小布 accompany age_years），
每轮对话用当前年月重算，过生日自动升档。档位串供 #5（灰色话题档）
与 #7/#8（后台任务）复用；生日缺失/非法返回 None，退化为无年龄分档。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

_BIRTH_YM_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

AGE_BAND_3_5 = "3-5 岁"
AGE_BAND_6_8 = "6-8 岁"
AGE_BAND_9_PLUS = "9 岁以上"


def _today() -> date:
    return date.today()


def _ym_to_months(birth_ym: Optional[str]) -> Optional[int]:
    """出生年月 → 月计数（y*12 + (m-1)）；格式非法返回 None。"""
    if not isinstance(birth_ym, str):
        return None
    m = _BIRTH_YM_RE.match(birth_ym.strip())
    if not m:
        return None
    y, month = int(m.group(1)), int(m.group(2))
    return y * 12 + (month - 1)


def age_years(birth_ym: Optional[str], now: date = None) -> Optional[int]:
    """满岁数（月粒度）；生日缺失/非法/晚于当前年月返回 None。"""
    birth = _ym_to_months(birth_ym)
    if birth is None:
        return None
    current = now or _today()
    cur_months = current.year * 12 + (current.month - 1)
    if birth > cur_months:
        return None
    return (cur_months - birth) // 12


def age_band(birth_ym: Optional[str], now: date = None) -> Optional[str]:
    """生日 → 年龄档位串（3-5 岁 / 6-8 岁 / 9 岁以上）；非法返回 None。"""
    age = age_years(birth_ym, now)
    if age is None:
        return None
    if age <= 5:
        return AGE_BAND_3_5
    if age <= 8:
        return AGE_BAND_6_8
    return AGE_BAND_9_PLUS


def _clean(value) -> str:
    """去空白；非字符串/空返回空串。"""
    return value.strip() if isinstance(value, str) else ""


def render_kids_profile(kids_cfg: Optional[dict], now: date = None) -> str:
    """kids 配置块 → L2 档案层文案（小布逐字契约）。

    - 未开 enabled / 无可渲染内容 → 空串（空层跳过，不断对话）
    - 生日非法/缺失 → 跳过年龄行，其余行照常（退化为无年龄分档）
    - 档位串只填「按%s孩子的理解和话题深度对话」单句槽位
    """
    if not isinstance(kids_cfg, dict) or not kids_cfg.get("enabled"):
        return ""

    lines: list[str] = ["【你陪伴的孩子】"]
    nickname = _clean(kids_cfg.get("nickname"))
    if nickname:
        lines.append(f"称呼：{nickname}（平时就这么叫他）")
    age = age_years(kids_cfg.get("birth_ym"), now)
    if age is not None:
        lines.append(f"年龄：约 {age} 岁，按{age_band(kids_cfg.get('birth_ym'), now)}孩子的理解和话题深度对话")
    personality = _clean(kids_cfg.get("personality"))
    if personality:
        lines.append(f"性格：{personality}")
    hobbies = _clean(kids_cfg.get("hobbies"))
    if hobbies:
        lines.append(f"爱好：{hobbies}")

    sections = ["\n".join(lines)]
    instructions = _clean(kids_cfg.get("instructions"))
    if instructions:
        sections.append(f"【家长嘱托，记在心里】\n{instructions}")

    taboos = kids_cfg.get("taboos")
    if isinstance(taboos, str):
        taboos = [taboos]
    entries = [t.strip() for t in taboos if isinstance(t, str) and t.strip()] if isinstance(taboos, list) else []
    if entries:
        bullets = "\n".join(f"- {t}" for t in entries)
        sections.append(
            "【家长定的禁忌，必须做到】\n"
            "孩子提到下面任何一条，就温柔地换个话题，不解释原因：\n"
            f"{bullets}"
        )

    if len(sections) == 1 and len(lines) == 1:
        return ""  # 只有段标题没有任何档案行 → 空层
    return "\n\n".join(sections)
