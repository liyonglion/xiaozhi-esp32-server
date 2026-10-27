package xiaozhi.modules.todo.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@TableName("todo_daily_template")
@Schema(description = "每日任务模板（每天 0 点重建当日清单的种子）")
public class TodoDailyTemplateEntity {

    @TableId(type = IdType.ASSIGN_UUID)
    @Schema(description = "模板ID")
    private String id;

    @Schema(description = "设备MAC地址")
    private String macAddress;

    @Schema(description = "分组：morning/study/chores/bedtime")
    private String groupKey;

    @Schema(description = "任务文本（≤30字）")
    private String text;

    @Schema(description = "可选截止时刻 HH:MM（T4 提醒消费，本票仅存值）")
    private String deadline;

    @Schema(description = "显示序（保存顺序）")
    private Integer sort;

    @Schema(description = "创建者")
    private Long creator;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新者")
    private Long updater;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
