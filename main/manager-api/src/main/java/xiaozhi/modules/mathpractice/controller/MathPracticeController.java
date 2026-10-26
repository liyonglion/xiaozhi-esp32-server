package xiaozhi.modules.mathpractice.controller;

import java.io.IOException;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;
import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.Parameters;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.page.PageData;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.mathpractice.dto.MathPracticeConfigSaveDTO;
import xiaozhi.modules.mathpractice.service.MathPracticeService;
import xiaozhi.modules.mathpractice.vo.MathPracticeConfigVO;
import xiaozhi.modules.mathpractice.vo.MathPracticeProgressVO;

@RestController
@RequestMapping("/math-practice")
@Tag(name = "口算练习管理")
public class MathPracticeController {

    private final MathPracticeService mathPracticeService;

    /** P2 屏进度接口令牌（#29：部署时与固件约定；空=拒绝所有，公网 IP 枚举面） */
    private final String progressToken;

    public MathPracticeController(MathPracticeService mathPracticeService,
            @Value("${math-practice.progress-token:}") String progressToken) {
        this.mathPracticeService = mathPracticeService;
        this.progressToken = progressToken;
    }

    @GetMapping("/progress")
    @Operation(summary = "P2 学习进度屏全量聚合（固件开机首拉 + xiaozhi-server 推送前数据源，鉴权 X-Progress-Token 头）")
    public Result<MathPracticeProgressVO> getProgress(
            @RequestParam String macAddress,
            @RequestHeader(value = "X-Progress-Token", required = false) String token,
            HttpServletResponse response) throws IOException {
        // 常量时间比较防时序侧信道（token 为固件共享单一值，枚举面靠它收敛，#29）
        if (StringUtils.isBlank(progressToken) || token == null
                || !java.security.MessageDigest.isEqual(
                        progressToken.getBytes(java.nio.charset.StandardCharsets.UTF_8),
                        token.getBytes(java.nio.charset.StandardCharsets.UTF_8))) {
            response.sendError(HttpServletResponse.SC_UNAUTHORIZED);
            return null;
        }
        return new Result<MathPracticeProgressVO>().ok(mathPracticeService.getProgress(macAddress));
    }

    @GetMapping("/config")
    @Operation(summary = "获取设备口算练习配置")
    @RequiresPermissions("sys:role.normal")
    public Result<MathPracticeConfigVO> getConfig(@RequestParam String macAddress) {
        MathPracticeConfigVO vo = mathPracticeService.getConfigForUser(macAddress);
        return new Result<MathPracticeConfigVO>().ok(vo);
    }

    @PutMapping("/config")
    @Operation(summary = "保存设备口算练习配置")
    @RequiresPermissions("sys:role.normal")
    public Result<MathPracticeConfigVO> saveConfig(@Valid @RequestBody MathPracticeConfigSaveDTO dto) {
        MathPracticeConfigVO vo = mathPracticeService.saveConfig(dto);
        return new Result<MathPracticeConfigVO>().ok(vo);
    }

    @GetMapping("/record/list")
    @Operation(summary = "分页获取设备练习记录")
    @RequiresPermissions("sys:role.normal")
    @Parameters({
            @Parameter(name = Constant.PAGE, description = "当前页码，从1开始", required = true),
            @Parameter(name = Constant.LIMIT, description = "每页显示记录数", required = true),
            @Parameter(name = "macAddress", description = "设备MAC地址", required = true),
    })
    public Result<PageData<Map<String, Object>>> listRecords(
            @Parameter(hidden = true) @RequestParam Map<String, Object> params) {
        PageData<Map<String, Object>> page = mathPracticeService.listRecords(params);
        return new Result<PageData<Map<String, Object>>>().ok(page);
    }
}
