package xiaozhi.modules.agent.vo;

import java.util.Date;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * 儿童陪伴模式拦截日志VO（家长页展示）
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
@Data
public class AgentInterceptionLogVO {
    @Schema(description = "主键ID")
    private Long id;

    @Schema(description = "拦截类别: care/redline/danger/privacy/profanity")
    private String category;

    @Schema(description = "孩子原话")
    private String userText;

    @Schema(description = "模型原回复")
    private String modelReply;

    @Schema(description = "孩子实际听到的内容")
    private String actualReply;

    @Schema(description = "拦截发生时间")
    private Date occurredAt;
}
