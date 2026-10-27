package xiaozhi.modules.todo.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@TableName("todo_event")
@Schema(description = "设备任务完成事件（上报与旧镜像 diff 出「由未完成变为完成」逐次记录）")
public class TodoEventEntity {

    @TableId(type = IdType.ASSIGN_UUID)
    @Schema(description = "事件ID")
    private String id;

    @Schema(description = "设备MAC地址")
    private String macAddress;

    @Schema(description = "完成时的任务文本")
    private String text;

    @Schema(description = "完成时间")
    private Date createdAt;
}
