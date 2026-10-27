package xiaozhi.modules.todo.vo;

import java.util.Date;
import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import xiaozhi.modules.todo.dto.TodoItemDTO;

@Data
@Schema(description = "设备任务清单镜像 + 设备级配置（家长只读）")
public class TodoMirrorVO {

    @Schema(description = "设备MAC地址")
    private String mac;

    @Schema(description = "全量清单")
    private List<TodoItemDTO> items;

    @Schema(description = "同步开关（设备级）")
    private boolean syncEnabled;

    @Schema(description = "提醒静默起始 HH:MM")
    private String quietStart;

    @Schema(description = "提醒静默结束 HH:MM")
    private String quietEnd;

    @Schema(description = "清单条数软上限")
    private Integer maxItems;

    @Schema(description = "待下发标记")
    private boolean pending;

    @Schema(description = "最近一次写入来源")
    private String source;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
