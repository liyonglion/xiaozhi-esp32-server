package xiaozhi.modules.todo.controller;

import java.util.List;

import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.AllArgsConstructor;
import xiaozhi.common.utils.Result;
import xiaozhi.common.validator.ValidatorUtils;
import xiaozhi.modules.todo.dto.TodoDailyItemDTO;
import xiaozhi.modules.todo.dto.TodoDailySaveDTO;
import xiaozhi.modules.todo.dto.TodoReportDTO;
import xiaozhi.modules.todo.service.TodoService;
import xiaozhi.modules.todo.vo.TodoMirrorVO;

@RestController
@RequestMapping("/todo-list")
@Tag(name = "设备任务清单")
@AllArgsConstructor
public class TodoController {

    private final TodoService todoService;

    @GetMapping
    @Operation(summary = "按 mac 查设备任务清单镜像与设备级配置（spec #30）")
    @RequiresPermissions("sys:role.normal")
    public Result<TodoMirrorVO> getMirror(@RequestParam String macAddress) {
        return new Result<TodoMirrorVO>().ok(todoService.getMirrorForUser(macAddress));
    }

    @PutMapping
    @Operation(summary = "整表保存（#32：>30 条拒绝、单条 30 字截断；存镜像置 pending，由 60s 循环对在线设备下发；#33：设备级配置随整表一并提交）")
    @RequiresPermissions("sys:role.normal")
    public Result<TodoMirrorVO> save(@RequestBody TodoReportDTO dto) {
        ValidatorUtils.validateEntity(dto);
        return new Result<TodoMirrorVO>().ok(todoService.saveTodoListForUser(dto));
    }

    @GetMapping("/daily")
    @Operation(summary = "查询每日任务模板（#33：四组，按保存顺序）")
    @RequiresPermissions("sys:role.normal")
    public Result<List<TodoDailyItemDTO>> getDaily(@RequestParam String macAddress) {
        return new Result<List<TodoDailyItemDTO>>().ok(todoService.getDailyForUser(macAddress));
    }

    @PutMapping("/daily")
    @Operation(summary = "整组保存每日任务模板（#33：全量替换；分组白名单、30 字截断、≤30 条）")
    @RequiresPermissions("sys:role.normal")
    public Result<List<TodoDailyItemDTO>> saveDaily(@RequestBody TodoDailySaveDTO dto) {
        ValidatorUtils.validateEntity(dto);
        return new Result<List<TodoDailyItemDTO>>().ok(todoService.saveDailyForUser(dto));
    }
}
