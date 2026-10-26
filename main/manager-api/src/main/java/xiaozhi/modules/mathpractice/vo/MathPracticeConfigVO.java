package xiaozhi.modules.mathpractice.vo;

import java.util.Date;
import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "口算练习设备配置")
public class MathPracticeConfigVO {

    @Schema(description = "设备MAC地址")
    private String macAddress;

    @Schema(description = "年级预设")
    private String preset;

    @Schema(description = "题型ID集合（微调后的实际值）")
    private List<String> typeIds;

    @Schema(description = "每轮题量")
    private Integer questionCount;

    @Schema(description = "最近一场收尾连对值（xiaozhi-server 续接 seed 用；未配置设备也返回）")
    private Integer streakEnd;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
