package xiaozhi.modules.mathpractice.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@TableName("math_practice_record")
@Schema(description = "口算练习记录（一次会话一行）")
public class MathPracticeRecordEntity {

    @TableId(type = IdType.ASSIGN_UUID)
    @Schema(description = "记录ID")
    private String id;

    @Schema(description = "设备MAC地址")
    private String macAddress;

    @Schema(description = "当时使用的年级预设")
    private String preset;

    @Schema(description = "本轮题量")
    private Integer total;

    @Schema(description = "答对题数")
    private Integer correct;

    @Schema(description = "本轮用时（秒）")
    private Integer durationSeconds;

    @Schema(description = "练习时间")
    private Date createdAt;
}
