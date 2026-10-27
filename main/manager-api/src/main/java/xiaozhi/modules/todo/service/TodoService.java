package xiaozhi.modules.todo.service;

import java.util.List;

import xiaozhi.modules.todo.dto.TodoReportDTO;
import xiaozhi.modules.todo.vo.TodoMirrorVO;

public interface TodoService {

    /** 设备全量清单上报：存镜像，并与旧镜像 diff 出「由未完成变为完成」事件入库 */
    void reportTodoMirror(TodoReportDTO dto);

    /** 按 mac 查镜像与设备级配置（不做属主校验，供设备侧/定时任务复用） */
    TodoMirrorVO getMirror(String macAddress);

    /** 家长只读查询（校验设备属主） */
    TodoMirrorVO getMirrorForUser(String macAddress);

    /** 家长整表保存（T2）：>30 条拒绝、单条 30 字截断；存镜像置 pending，返回含在线/pending 状态 */
    TodoMirrorVO saveTodoListForUser(TodoReportDTO dto);

    /** 下发循环拉取待下发清单（xiaozhi-server 每 60s 调用；仅 pending 且同步开关开的设备） */
    List<TodoMirrorVO> getPendingMirrors();

    /** 下发回执（T2）：set_todos(replace) receipt ok 后清 pending；镜像内容已被更新保存时保留 pending */
    void markDelivered(TodoReportDTO dto);
}
