package xiaozhi.modules.todo.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "任务项（设备契约 {text,done} 不可扩；due 为服务端侧截止时刻，下发设备前剥离）")
public class TodoItemDTO {

    @Schema(description = "任务文本（≤30字，超长截断）")
    private String text;

    @Schema(description = "是否完成")
    private Boolean done;

    @JsonInclude(JsonInclude.Include.NON_NULL)
    @Schema(description = "截止时刻 HH:MM（服务端侧字段：提醒翻译用；设备契约不含此字段，下发前剥离）")
    private String due;
}
