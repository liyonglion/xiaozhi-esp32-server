package xiaozhi.modules.mathpractice.vo;

import java.util.List;
import java.util.Map;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * P2 学习进度屏全量聚合（#29）。固件无状态：开机 HTTP 首拉与 xiaozhi-server 判决后
 * MCP update_progress 推送共用本结构，8 字段 + weekCorrect/weekTotal（供 python 叠加
 * 进行中会话重算 weekAccuracy，固件忽略）。
 */
@Data
@Schema(description = "口算练习学习进度（全量）")
public class MathPracticeProgressVO {

    @Schema(description = "今日答对题数")
    private Integer todayCorrect;

    @Schema(description = "今日作答题数")
    private Integer todayTotal;

    @Schema(description = "今日单会话最高连对")
    private Integer todayMaxStreak;

    @Schema(description = "当前连对（最近一场收尾 streak_end；进行中由推送叠加）")
    private Integer currentStreak;

    @Schema(description = "历史最高连对（全史 MAX(streak_peak)）")
    private Integer bestStreak;

    @Schema(description = "近 7 天正确率（0-100 整数百分比，无数据为 0）")
    private Integer weekAccuracy;

    @Schema(description = "近 7 天答对题数（python 叠加用）")
    private Integer weekCorrect;

    @Schema(description = "近 7 天作答题数（python 叠加用）")
    private Integer weekTotal;

    @Schema(description = "最近 5 场：time/correct/total/streakPeak")
    private List<Map<String, Object>> recentSessions;
}
