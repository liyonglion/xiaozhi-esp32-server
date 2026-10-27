package xiaozhi.modules.todo.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.MockedStatic;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;

import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.JsonUtils;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.modules.todo.dao.TodoDailyTemplateDao;
import xiaozhi.modules.todo.dao.TodoEventDao;
import xiaozhi.modules.todo.dao.TodoMirrorDao;
import xiaozhi.modules.todo.dto.TodoDailyItemDTO;
import xiaozhi.modules.todo.dto.TodoItemDTO;
import xiaozhi.modules.todo.dto.TodoReportDTO;
import xiaozhi.modules.todo.entity.TodoDailyTemplateEntity;
import xiaozhi.modules.todo.entity.TodoMirrorEntity;
import xiaozhi.modules.todo.service.TodoOnlineRegistry;
import xiaozhi.modules.todo.vo.TodoMirrorVO;

/** T4（#34）：截止时刻 due——服务端侧字段，存镜像 items JSON、API 透出、模板 deadline 被重建消费。 */
class TodoServiceImplDueTest {

    private static final long USER_ID = 42L;

    @BeforeAll
    static void initTableInfo() {
        TableInfoHelper.initTableInfo(new org.apache.ibatis.builder.MapperBuilderAssistant(
                new MybatisConfiguration(), ""), TodoMirrorEntity.class);
        TableInfoHelper.initTableInfo(new org.apache.ibatis.builder.MapperBuilderAssistant(
                new MybatisConfiguration(), ""), TodoDailyTemplateEntity.class);
    }

    static TodoItemDTO item(String text, boolean done) {
        TodoItemDTO i = new TodoItemDTO();
        i.setText(text);
        i.setDone(done);
        return i;
    }

    static TodoItemDTO item(String text, boolean done, String due) {
        TodoItemDTO i = item(text, done);
        i.setDue(due);
        return i;
    }

    static TodoReportDTO report(String mac, TodoItemDTO... items) {
        TodoReportDTO dto = new TodoReportDTO();
        dto.setMacAddress(mac);
        dto.setItems(List.of(items));
        return dto;
    }

    static TodoMirrorEntity storedMirror(String mac, TodoItemDTO... items) {
        TodoMirrorEntity e = new TodoMirrorEntity();
        e.setId("row-1");
        e.setMacAddress(mac);
        e.setItems(JsonUtils.toJsonString(List.of(items)));
        e.setSyncEnabled(1);
        e.setPending(0);
        return e;
    }

    static DeviceService ownedDeviceService() {
        DeviceService deviceService = mock(DeviceService.class);
        DeviceEntity d = new DeviceEntity();
        d.setUserId(USER_ID);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(d);
        return deviceService;
    }

    static TodoServiceImpl newService(TodoMirrorDao mirrorDao, TodoDailyTemplateDao dailyDao) {
        return new TodoServiceImpl(mirrorDao, mock(TodoEventDao.class), ownedDeviceService(),
                new TodoOnlineRegistry(), dailyDao);
    }

    // ───────────────────────── due 存取与透出 ─────────────────────────

    @Test
    void saveKeepsDueInMirrorJsonAndExposesInMirrorVO() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        // 首查无行（insert 路径）；保存写库后的重读（返回体供页面显示）
        TodoMirrorEntity saved = storedMirror("AA", item("写作业", false, "20:30"), item("刷牙", false));
        saved.setPending(1);
        when(mirrorDao.selectOne(any())).thenReturn(null, saved);
        TodoReportDTO dto = report("AA", item("写作业", false, "20:30"), item("刷牙", false));

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            TodoMirrorVO vo = newService(mirrorDao, mock(TodoDailyTemplateDao.class))
                    .saveTodoListForUser(dto);

            ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
            verify(mirrorDao).insert(captor.capture());
            List<TodoItemDTO> stored = TodoServiceImplTest.parseItems(captor.getValue().getItems());
            assertEquals("20:30", stored.get(0).getDue()); // due 落镜像 JSON
            assertNull(stored.get(1).getDue());
            assertEquals("20:30", vo.getItems().get(0).getDue()); // API 透出
        }
    }

    @Test
    void saveRejectsInvalidDueFormat() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        when(mirrorDao.selectOne(any())).thenReturn(null);

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            RenException ex = assertThrows(RenException.class, () -> newService(mirrorDao,
                    mock(TodoDailyTemplateDao.class)).saveTodoListForUser(report("AA",
                            item("写作业", false, "9:00"), item("刷牙", false, "24:00"))));
            assertTrue(ex.getMsg().contains("HH:MM"), "提示应说明 HH:MM 格式，实际: " + ex.getMsg());
        }
        verify(mirrorDao, never()).insert(any(TodoMirrorEntity.class)); // 拒绝即不落库
    }

    @Test
    void getMirrorExposesStoredDue() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        when(mirrorDao.selectOne(any())).thenReturn(storedMirror("AA", item("写作业", false, "20:30")));

        TodoMirrorVO vo = newService(mirrorDao, mock(TodoDailyTemplateDao.class)).getMirror("AA");

        assertEquals("20:30", vo.getItems().get(0).getDue());
    }

    @Test
    void pendingMirrorCarriesDueAndQuietConfigForAlarmTranslation() {
        // 下发链路（python）以 pending 行为提醒翻译数据源：items 带 due、设备级静默配置随行
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoMirrorEntity row = storedMirror("AA", item("写作业", false, "20:30"));
        row.setPending(1);
        row.setQuietStart("22:00");
        row.setQuietEnd("08:00");
        when(mirrorDao.selectList(any())).thenReturn(List.of(row));

        List<TodoMirrorVO> pending = newService(mirrorDao, mock(TodoDailyTemplateDao.class)).getPendingMirrors();

        assertEquals(1, pending.size());
        assertEquals("20:30", pending.get(0).getItems().get(0).getDue());
        assertEquals("22:00", pending.get(0).getQuietStart());
        assertEquals("08:00", pending.get(0).getQuietEnd());
    }

    // ───────────────────────── 语音上报按文本续期 due（设备 receipt 无 due 概念） ─────────────────────────

    @Test
    void voiceReportCarriesDueForwardByMatchingText() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        // 旧镜像：写作业 due 20:30 未完成、读绘本 due 19:00 未完成
        when(mirrorDao.selectOne(any())).thenReturn(
                storedMirror("AA", item("写作业", false, "20:30"), item("读绘本", false, "19:00")));

        // 语音操作后：写作业完成（保留 due）、读绘本被删（due 随任务消失）、收拾玩具新增（无 due）
        newService(mirrorDao, mock(TodoDailyTemplateDao.class)).reportTodoMirror(report("AA",
                item("写作业", true), item("收拾玩具", false)));

        ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
        verify(mirrorDao).updateById(captor.capture());
        List<TodoItemDTO> stored = TodoServiceImplTest.parseItems(captor.getValue().getItems());
        assertEquals("20:30", stored.get(0).getDue()); // 同文本任务：due 随清单留存
        assertNull(stored.get(1).getDue()); // 新任务无 due
        assertEquals(2, stored.size()); // 被删任务的 due 一并消失
    }

    // ───────────────────────── 0 点重建消费模板 deadline ─────────────────────────

    @Test
    void dailyRebuildInjectsTemplateDeadlineAsItemDue() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        TodoDailyTemplateEntity tpl = new TodoDailyTemplateEntity();
        tpl.setMacAddress("AA");
        tpl.setGroupKey("bedtime");
        tpl.setText("睡前刷牙");
        tpl.setDeadline("21:00");
        tpl.setSort(0);
        TodoDailyTemplateEntity tplNoDue = new TodoDailyTemplateEntity();
        tplNoDue.setMacAddress("AA");
        tplNoDue.setGroupKey("study");
        tplNoDue.setText("写作业");
        tplNoDue.setSort(1);
        when(dailyDao.selectList(any())).thenReturn(List.of(tpl, tplNoDue));
        // 存量手动项：due 应原样保留
        when(mirrorDao.selectOne(any())).thenReturn(storedMirror("AA", item("修玩具", false, "18:00")));

        newService(mirrorDao, dailyDao).rebuildDailyLists();

        ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
        verify(mirrorDao).updateById(captor.capture());
        List<TodoItemDTO> merged = TodoServiceImplTest.parseItems(captor.getValue().getItems());
        assertEquals("21:00", merged.get(0).getDue()); // 模板 deadline → 当日项 due
        assertNull(merged.get(1).getDue());
        assertEquals("18:00", merged.get(2).getDue()); // 手动项 due 保留
    }

    // ───────────────────────── 送达回执：设备 echo 无 due 不挡 pending 清除 ─────────────────────────

    @Test
    void markDeliveredClearsPendingWhenEchoLacksDue() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoMirrorEntity stored = storedMirror("AA", item("写作业", false, "20:30"));
        stored.setPending(1);
        when(mirrorDao.selectOne(any())).thenReturn(stored);
        when(mirrorDao.update(any(), any())).thenReturn(1); // 条件命中 → pending 清

        // 设备 receipt 只回 {text,done}：{text,done} 投影一致即视为内容未变
        newService(mirrorDao, mock(TodoDailyTemplateDao.class))
                .markDelivered(report("AA", item("写作业", false)));

        verify(mirrorDao).update(any(), any());
    }

    @Test
    void markDeliveredKeepsPendingWhenTextsChanged() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoMirrorEntity stored = storedMirror("AA", item("写作业", false, "20:30"));
        stored.setPending(1);
        when(mirrorDao.selectOne(any())).thenReturn(stored);

        // 送达期间家长又保存（文本变化）：投影不一致 → 不清 pending
        newService(mirrorDao, mock(TodoDailyTemplateDao.class))
                .markDelivered(report("AA", item("新任务", false)));

        verify(mirrorDao, never()).update(any(), any());
    }

    // ───────────────────────── 每日模板 API 透出 deadline（T3 已有列，此处确认 DTO 往返） ─────────────────────────

    @Test
    void dailyTemplateDtoRoundTripsDeadline() {
        TodoDailyItemDTO dto = new TodoDailyItemDTO();
        dto.setGroup("bedtime");
        dto.setText("睡前刷牙");
        dto.setDeadline("21:00");
        TodoDailyTemplateEntity entity = new TodoDailyTemplateEntity();
        entity.setGroupKey(dto.getGroup());
        entity.setText(dto.getText());
        entity.setDeadline(dto.getDeadline());

        assertEquals("21:00", entity.getDeadline());
        assertEquals("bedtime", entity.getGroupKey());
    }
}
