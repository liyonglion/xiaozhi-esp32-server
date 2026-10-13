package xiaozhi.modules.agent.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

/**
 * 小智服务儿童模式拦截日志上报请求
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
@Data
@Schema(description = "小智服务儿童模式拦截日志上报请求")
public class AgentInterceptionLogReportDTO {
    @Schema(description = "MAC地址", example = "00:11:22:33:44:55")
    @NotBlank
    private String macAddress;

    @Schema(description = "拦截事件列表（回合结束整批上报）")
    @NotEmpty
    @Valid
    private List<Item> interceptions;

    /**
     * 单条拦截事件（与 Python 侧统一 dict 结构对齐：t/when/cat/user/reply/actual；
     * when 为展示串，由 occurred_at 派生，不入库）
     */
    @Data
    public static class Item {
        @Schema(description = "拦截发生时间（epoch 秒）", example = "1745657732.5")
        @NotNull
        private Double t;

        @Schema(description = "拦截类别: care/redline/danger/privacy/profanity", example = "redline")
        @NotBlank
        private String cat;

        @Schema(description = "孩子原话", example = "给我讲个鬼故事")
        private String user;

        @Schema(description = "模型原回复", example = "从前有一个……")
        private String reply;

        @Schema(description = "孩子实际听到的内容", example = "咦，这个我还真不知道呢。")
        private String actual;
    }
}
