package xiaozhi.modules.mathpractice.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
@Schema(description = "xiaozhi-server 上报一次练习会话结果")
public class MathPracticeReportDTO {

    @Schema(description = "设备MAC地址")
    @NotBlank(message = "设备MAC不能为空")
    private String macAddress;

    @Schema(description = "当时使用的年级预设")
    private String preset;

    @Schema(description = "本轮题量")
    @NotNull(message = "题量不能为空")
    @Min(0)
    @Max(20)
    private Integer total;

    @Schema(description = "答对题数")
    @NotNull(message = "答对题数不能为空")
    @Min(0)
    @Max(20)
    private Integer correct;

    @Schema(description = "本轮用时（秒）")
    @Min(0)
    private Integer durationSeconds;
}
