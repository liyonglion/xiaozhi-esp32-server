package xiaozhi.modules.mathpractice.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@TableName("math_practice_config")
@Schema(description = "口算练习设备配置")
public class MathPracticeConfigEntity {

    @TableId(type = IdType.ASSIGN_UUID)
    @Schema(description = "配置ID")
    private String id;

    @Schema(description = "设备MAC地址")
    private String macAddress;

    @Schema(description = "年级预设：preschool/g1a/g1b/g2a/g2b")
    private String preset;

    @Schema(description = "微调后的题型ID集合（逗号分隔），空=使用预设默认")
    private String typeIds;

    @Schema(description = "每轮题量（5-20）")
    private Integer questionCount;

    @Schema(description = "创建者")
    private Long creator;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新者")
    private Long updater;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
