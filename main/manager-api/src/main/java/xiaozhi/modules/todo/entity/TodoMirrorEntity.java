package xiaozhi.modules.todo.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@TableName("todo_mirror")
@Schema(description = "设备任务清单镜像（设备 NVS 为唯一真值源，此为服务端镜像）")
public class TodoMirrorEntity {

    @TableId(type = IdType.ASSIGN_UUID)
    @Schema(description = "镜像ID")
    private String id;

    @Schema(description = "设备MAC地址")
    private String macAddress;

    @Schema(description = "清单镜像 JSON 数组 [{\"text\":..,\"done\":..}]")
    private String items;

    @Schema(description = "同步开关（设备级，1=开 0=关）")
    private Integer syncEnabled;

    @Schema(description = "提醒静默起始 HH:MM")
    private String quietStart;

    @Schema(description = "提醒静默结束 HH:MM")
    private String quietEnd;

    @Schema(description = "清单条数软上限")
    private Integer maxItems;

    @Schema(description = "待下发标记（1=家长编辑后等待送达设备）")
    private Integer pending;

    @Schema(description = "最近一次镜像写入来源：voice/admin/daily")
    private String source;

    @Schema(description = "创建者")
    private Long creator;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新者")
    private Long updater;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
