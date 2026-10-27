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
}
