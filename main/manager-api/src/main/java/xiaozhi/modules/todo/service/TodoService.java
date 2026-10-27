package xiaozhi.modules.todo.service;

import xiaozhi.modules.todo.dto.TodoReportDTO;
import xiaozhi.modules.todo.vo.TodoMirrorVO;

public interface TodoService {

    /** 设备全量清单上报：存镜像，并与旧镜像 diff 出「由未完成变为完成」事件入库 */
    void reportTodoMirror(TodoReportDTO dto);

    /** 按 mac 查镜像与设备级配置（不做属主校验，供设备侧/定时任务复用） */
    TodoMirrorVO getMirror(String macAddress);

    /** 家长只读查询（校验设备属主） */
    TodoMirrorVO getMirrorForUser(String macAddress);
}
