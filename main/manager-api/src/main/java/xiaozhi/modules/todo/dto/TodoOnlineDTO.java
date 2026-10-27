package xiaozhi.modules.todo.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
@Schema(description = "xiaozhi-server 周期上报在线 mac 集合（T2：家长页在线/离线徽标数据源）")
public class TodoOnlineDTO {

    @Schema(description = "当前在线设备 mac 全量集合")
    @NotNull(message = "在线集合不能为空")
    private List<String> macs;
}
