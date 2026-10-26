package xiaozhi.modules.config.controller;

import java.util.List;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.AllArgsConstructor;
import xiaozhi.common.utils.Result;
import xiaozhi.common.validator.ValidatorUtils;
import xiaozhi.modules.config.dto.AgentModelsDTO;
import xiaozhi.modules.config.dto.CorrectWordsDTO;
import xiaozhi.modules.config.service.ConfigService;
import xiaozhi.modules.mathpractice.dto.MathPracticeReportDTO;
import xiaozhi.modules.mathpractice.service.MathPracticeService;
import xiaozhi.modules.mathpractice.vo.MathPracticeConfigVO;

/**
 * xiaozhi-server 配置获取
 *
 * @since 1.0.0
 */
@RestController
@RequestMapping("config")
@Tag(name = "参数管理")
@AllArgsConstructor
public class ConfigController {
    private final ConfigService configService;
    private final MathPracticeService mathPracticeService;

    @PostMapping("server-base")
    @Operation(summary = "服务端获取配置接口")
    public Result<Object> getConfig() {
        Object config = configService.getConfig(true);
        return new Result<Object>().ok(config);
    }

    @PostMapping("agent-models")
    @Operation(summary = "获取智能体模型")
    public Result<Object> getAgentModels(@Valid @RequestBody AgentModelsDTO dto) {
        // 效验数据
        ValidatorUtils.validateEntity(dto);
        Object models = configService.getAgentModels(dto.getMacAddress(), dto.getSelectedModule());
        return new Result<Object>().ok(models);
    }

    @PostMapping("correct-words")
    @Operation(summary = "获取智能体替换词")
    public Result<Object> getCorrectWords(@Valid @RequestBody CorrectWordsDTO dto) {
        ValidatorUtils.validateEntity(dto);
        List<String> list = configService.getCorrectWords(dto.getMacAddress());
        return new Result<Object>().ok(list);
    }

    @PostMapping("math-practice")
    @Operation(summary = "获取设备口算练习配置（未配置返回 null，由 python 侧回落默认档）")
    public Result<MathPracticeConfigVO> getMathPracticeConfig(@Valid @RequestBody CorrectWordsDTO dto) {
        ValidatorUtils.validateEntity(dto);
        MathPracticeConfigVO vo = mathPracticeService.getConfigByMac(dto.getMacAddress());
        return new Result<MathPracticeConfigVO>().ok(vo);
    }

    @PostMapping("math-practice/report")
    @Operation(summary = "上报一次口算练习会话结果")
    public Result<Void> reportMathPractice(@Valid @RequestBody MathPracticeReportDTO dto) {
        ValidatorUtils.validateEntity(dto);
        mathPracticeService.reportRecord(dto);
        return new Result<Void>();
    }
}
