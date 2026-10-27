package xiaozhi.modules.todo.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
@Schema(description = "家长整组保存每日任务模板（全量替换）")
public class TodoDailySaveDTO {

    @Schema(description = "设备MAC地址")
    @NotBlank(message = "设备MAC不能为空")
    private String macAddress;

    @Schema(description = "模板全量（空数组=清空该设备全部模板）")
    @NotNull(message = "模板清单不能为空")
    @Valid
    private List<TodoDailyItemDTO> items;
}
