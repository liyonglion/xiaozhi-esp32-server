package xiaozhi.modules.config.controller;

import java.util.List;

import org.springframework.web.bind.annotation.GetMapping;
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
import xiaozhi.modules.todo.dto.TodoOnlineDTO;
import xiaozhi.modules.todo.dto.TodoReportDTO;
import xiaozhi.modules.todo.service.TodoOnlineRegistry;
import xiaozhi.modules.todo.service.TodoService;
import xiaozhi.modules.todo.vo.TodoMirrorVO;

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
    private final TodoService todoService;
    private final TodoOnlineRegistry todoOnlineRegistry;

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
    @Operation(summary = "获取设备口算练习配置（#29：未配置也返回体，preset 等空由 python 回落默认档；streakEnd 随体捎回）")
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

    @PostMapping("todo-list/report")
    @Operation(summary = "上报设备全量任务清单（spec #30 T1：set_todos receipt 挂钩，存镜像并 diff 完成事件）")
    public Result<Void> reportTodoList(@Valid @RequestBody TodoReportDTO dto) {
        ValidatorUtils.validateEntity(dto);
        todoService.reportTodoMirror(dto);
        return new Result<Void>();
    }

    @GetMapping("todo-list/pending")
    @Operation(summary = "拉取待下发清单（#32：60s 同步循环扫描，仅 pending 且同步开关开的设备）")
    public Result<List<TodoMirrorVO>> getTodoPending() {
        return new Result<List<TodoMirrorVO>>().ok(todoService.getPendingMirrors());
    }

    @PostMapping("todo-list/delivered")
    @Operation(summary = "下发回执（#32：set_todos(replace) receipt ok 后清 pending；镜像已被更新保存时保留 pending）")
    public Result<Void> reportTodoDelivered(@Valid @RequestBody TodoReportDTO dto) {
        ValidatorUtils.validateEntity(dto);
        todoService.markDelivered(dto);
        return new Result<Void>();
    }

    @PostMapping("todo-list/online")
    @Operation(summary = "上报在线 mac 集合（#32：xiaozhi-server 每 60s 全量上报，家长页在线徽标数据源）")
    public Result<Void> reportTodoOnline(@Valid @RequestBody TodoOnlineDTO dto) {
        ValidatorUtils.validateEntity(dto);
        todoOnlineRegistry.reportOnline(dto.getMacs());
        return new Result<Void>();
    }
}
