package xiaozhi.modules.mathpractice.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
@Schema(description = "保存口算练习设备配置")
public class MathPracticeConfigSaveDTO {

    @Schema(description = "设备MAC地址")
    @NotBlank(message = "设备MAC不能为空")
    private String macAddress;

    @Schema(description = "年级预设：preschool/g1a/g1b/g2a/g2b")
    @NotBlank(message = "年级预设不能为空")
    private String preset;

    @Schema(description = "微调后的题型ID集合，空=使用预设默认")
    private List<String> typeIds;

    @Schema(description = "每轮题量（5-20）")
    @Min(value = 5, message = "每轮题量最少5题")
    @Max(value = 20, message = "每轮题量最多20题")
    private Integer questionCount;
}
