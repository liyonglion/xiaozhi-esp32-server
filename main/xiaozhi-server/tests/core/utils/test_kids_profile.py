"""孩子档案年龄分档纯函数测试（工单 #6）。

被测契约（溯源小布（源工程）accompany age_years/age_band，月粒度）：
- 出生年月 "YYYY-MM" → 满岁数 = 月差 // 12，生日月即满岁
- 档位：age<=5 → "3-5 岁"；age<=8 → "6-8 岁"；否则 "9 岁以上"
- 生日缺失/非法/晚于当前年月 → None（退化为无年龄分档，不抛异常）

render_kids_profile 渲染 L2 档案层文案：小布（源工程）无独立档位文案，档位串只
填「按%s孩子的理解和话题深度对话」单句槽位；段标题是 prompt 契约，
保持小布（源工程）逐字。档位串是 #5（灰色话题档）与 #7/#8（后台任务）复用的
公共契约。
"""
from __future__ import annotations

from datetime import date

import pytest

from core.utils.kids_profile import age_band, age_years, render_kids_profile


class TestAgeYears:
    def test_birthday_month_counts_as_full_age(self):
        # 2019-05 → 2025-04：差 71 个月 = 5 岁（生日月未到）
        assert age_years("2019-05", now=date(2025, 4, 15)) == 5
        # 2019-05 → 2025-05：差 72 个月 = 6 岁（生日月即满岁）
        assert age_years("2019-05", now=date(2025, 5, 1)) == 6

    def test_same_month_is_age_zero(self):
        assert age_years("2025-10", now=date(2025, 10, 30)) == 0

    @pytest.mark.parametrize(
        "bad", ["garbage", "2019-13", "2019-5", "2019/05", "", None, "2019-05-01"]
    )
    def test_invalid_birth_returns_none(self, bad):
        assert age_years(bad) is None

    def test_future_birth_returns_none(self):
        # 晚于当前年月视为非法（小布（源工程）validate_profile 同规则）
        assert age_years("2060-01") is None


class TestAgeBand:
    def test_band_boundaries(self):
        # 5 岁 → 3-5 岁
        assert age_band("2020-01", now=date(2025, 12, 1)) == "3-5 岁"
        # 6 岁 → 6-8 岁（过生日升档）
        assert age_band("2019-06", now=date(2025, 6, 15)) == "6-8 岁"
        # 8 岁 → 6-8 岁
        assert age_band("2017-01", now=date(2025, 2, 1)) == "6-8 岁"
        # 9 岁 → 9 岁以上
        assert age_band("2016-05", now=date(2025, 5, 20)) == "9 岁以上"

    def test_band_upgrades_on_birthday_without_recalc_config(self):
        """同一生日，时间推进过生日月后档位自动升级（每轮按当前年月重算）。"""
        before = age_band("2019-06", now=date(2025, 5, 31))
        after = age_band("2019-06", now=date(2025, 6, 1))
        assert (before, after) == ("3-5 岁", "6-8 岁")

    def test_invalid_birth_returns_none(self):
        assert age_band("not-a-date") is None


FULL_PROFILE = {
    "enabled": True,
    "nickname": "小豆",
    "birth_ym": "2019-05",
    "personality": "好奇心重",
    "hobbies": "恐龙",
    "instructions": "睡前不讲吓人的故事",
    "taboos": ["不聊鬼故事", ""],
}


class TestRenderKidsProfile:
    def test_full_profile_renders_xiaobu_contract(self):
        """全档案渲染：段标题与小布（源工程）逐字，档位只填单句槽位。"""
        rendered = render_kids_profile(FULL_PROFILE, now=date(2025, 5, 20))
        assert rendered == (
            "【你陪伴的孩子】\n"
            "称呼：小豆（平时就这么叫他）\n"
            "年龄：约 6 岁，按6-8 岁孩子的理解和话题深度对话\n"
            "性格：好奇心重\n"
            "爱好：恐龙\n"
            "\n"
            "【家长嘱托，记在心里】\n"
            "睡前不讲吓人的故事\n"
            "\n"
            "【家长定的禁忌，必须做到】\n"
            "孩子提到下面任何一条，就温柔地换个话题，不解释原因：\n"
            "- 不聊鬼故事"
        )

    def test_missing_birth_degrades_to_no_age_line(self):
        """生日缺失/非法：不崩，其余档案行照常，只是没有年龄行。"""
        profile = {**FULL_PROFILE, "birth_ym": "2019-13"}
        rendered = render_kids_profile(profile, now=date(2025, 5, 20))
        assert "称呼：小豆" in rendered
        assert "年龄：" not in rendered
        assert "【家长嘱托，记在心里】" in rendered

    def test_disabled_or_empty_config_renders_empty(self):
        """未开开关/无配置 → 空串（L2 空层跳过）。"""
        assert render_kids_profile(None) == ""
        assert render_kids_profile({}) == ""
        assert render_kids_profile({**FULL_PROFILE, "enabled": False}) == ""

    def test_enabled_with_optional_fields_only_renders_partial(self):
        """只填部分可选字段：有啥渲染啥，无内容的行不出现。"""
        rendered = render_kids_profile(
            {"enabled": True, "nickname": "糖糖", "birth_ym": "2017-02"},
            now=date(2025, 5, 20),
        )
        assert rendered == (
            "【你陪伴的孩子】\n"
            "称呼：糖糖（平时就这么叫他）\n"
            "年龄：约 8 岁，按6-8 岁孩子的理解和话题深度对话"
        )

    def test_taboos_as_string_renders_single_entry(self):
        """taboos 给成单个字符串时按一条禁忌渲染（YAML 手写友好）。"""
        rendered = render_kids_profile(
            {"enabled": True, "nickname": "豆豆", "taboos": "不聊鬼故事"},
            now=date(2025, 5, 20),
        )
        assert "- 不聊鬼故事" in rendered
        assert "年龄：" not in rendered

