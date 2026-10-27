package xiaozhi.modules.todo.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
@Schema(description = "xiaozhi-server 上报设备全量任务清单（set_todos receipt）")
public class TodoReportDTO {

    @Schema(description = "设备MAC地址")
    @NotBlank(message = "设备MAC不能为空")
    private String macAddress;

    @Schema(description = "全量清单")
    @NotNull(message = "清单不能为空")
    @Valid
    private List<TodoItemDTO> items;

    // ── 设备级配置（#33 评论补充：家长页设备级配置块随整表保存一并提交；上报路径不传，null=不修改） ──

    @Schema(description = "同步开关（1=开 0=关；null=不修改）")
    private Boolean syncEnabled;

    @Schema(description = "提醒静默起始 HH:MM（null/空=不修改）")
    private String quietStart;

    @Schema(description = "提醒静默结束 HH:MM（null/空=不修改）")
    private String quietEnd;

    @Schema(description = "清单条数软上限 1-30（null=不修改）")
    private Integer maxItems;
}
