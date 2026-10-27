package xiaozhi.modules.todo.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "每日任务模板项（四组：morning/study/chores/bedtime）")
public class TodoDailyItemDTO {

    @Schema(description = "分组：morning/study/chores/bedtime")
    private String group;

    @Schema(description = "任务文本（≤30字，超长截断）")
    private String text;

    @Schema(description = "可选截止时刻 HH:MM（本票仅存值，T4 提醒消费）")
    private String deadline;
}
