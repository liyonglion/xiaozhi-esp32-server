package xiaozhi.modules.todo.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "任务项（设备契约不可扩：text ≤30 字，done 完成状态）")
public class TodoItemDTO {

    @Schema(description = "任务文本（≤30字，超长截断）")
    private String text;

    @Schema(description = "是否完成")
    private Boolean done;
}
