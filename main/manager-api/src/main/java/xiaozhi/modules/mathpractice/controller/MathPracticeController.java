package xiaozhi.modules.mathpractice.controller;

import java.util.Map;

import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.Parameters;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.AllArgsConstructor;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.page.PageData;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.mathpractice.dto.MathPracticeConfigSaveDTO;
import xiaozhi.modules.mathpractice.service.MathPracticeService;
import xiaozhi.modules.mathpractice.vo.MathPracticeConfigVO;

@RestController
@RequestMapping("/math-practice")
@Tag(name = "口算练习管理")
@AllArgsConstructor
public class MathPracticeController {

    private final MathPracticeService mathPracticeService;

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
