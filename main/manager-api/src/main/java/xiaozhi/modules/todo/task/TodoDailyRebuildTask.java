package xiaozhi.modules.todo.task;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import lombok.AllArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.modules.todo.service.TodoService;

/**
 * 每日任务 0 点重建（spec #30 / #33 T3）：当日清单 = 每日模板项（重置未完成）∪ 存量非每日手动项（留存）。
 * 结果写镜像、source=daily、置 pending，由 xiaozhi-server 既有 60s 下发通道送达（离线设备上线即达）。
 */
@Component
@AllArgsConstructor
@Slf4j
public class TodoDailyRebuildTask {

    private final TodoService todoService;

    /** 每天 0 点（Asia/Shanghai）；单进程单实例部署不会重复触发 */
    @Scheduled(cron = "0 0 0 * * *", zone = "Asia/Shanghai")
    public void rebuildDailyLists() {
        try {
            todoService.rebuildDailyLists();
        } catch (Exception e) {
            log.error("todo 每日重建任务异常", e); // 兜底：不让调度线程死掉，次日照常重建
        }
    }
}
