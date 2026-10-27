package xiaozhi.modules.todo.task;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import java.lang.reflect.Method;

import org.junit.jupiter.api.Test;
import org.springframework.scheduling.annotation.Scheduled;

import xiaozhi.common.exception.RenException;
import xiaozhi.modules.todo.service.TodoService;

/** 0 点触发点（#33）：cron 与时区是声明式接线，直接断言注解——等真 0 点不可测 */
class TodoDailyRebuildTaskTest {

    @Test
    void rebuildRunsAtMidnightShanghaiTime() throws Exception {
        Method rebuild = TodoDailyRebuildTask.class.getMethod("rebuildDailyLists");
        Scheduled scheduled = rebuild.getAnnotation(Scheduled.class);
        assertEquals("0 0 0 * * *", scheduled.cron(), "每天 0 点");
        assertEquals("Asia/Shanghai", scheduled.zone(), "spec #30 定死上海时区");
    }

    @Test
    void taskDelegatesToServiceAndSwallowsFailures() {
        TodoService service = mock(TodoService.class);
        TodoDailyRebuildTask task = new TodoDailyRebuildTask(service);

        task.rebuildDailyLists();
        verify(service).rebuildDailyLists();

        doThrow(new RenException("db down")).when(service).rebuildDailyLists();
        assertDoesNotThrow(task::rebuildDailyLists, "定时任务异常不得传播（照 DocumentStatusSyncTask 兜底）");
    }
}
