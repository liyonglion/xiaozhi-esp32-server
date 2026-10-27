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
import java.util.stream.Collectors;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.MockedStatic;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;

import xiaozhi.common.exception.RenException;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.modules.todo.dao.TodoDailyTemplateDao;
import xiaozhi.modules.todo.dao.TodoEventDao;
import xiaozhi.modules.todo.dao.TodoMirrorDao;
import xiaozhi.modules.todo.dto.TodoDailyItemDTO;
import xiaozhi.modules.todo.dto.TodoDailySaveDTO;
import xiaozhi.modules.todo.dto.TodoItemDTO;
import xiaozhi.modules.todo.dto.TodoReportDTO;
import xiaozhi.modules.todo.entity.TodoDailyTemplateEntity;
import xiaozhi.modules.todo.entity.TodoMirrorEntity;
import xiaozhi.modules.todo.service.TodoOnlineRegistry;

/**
 * T3（#33）：每日任务——模板管理 + 0 点重建语义 + 设备级配置随整表保存。
 * 照 TodoServiceImplTest 风格：纯 mock 单测，只测 service 公开行为。
 */
class TodoServiceImplDailyTest {

    private static final long USER_ID = 42L;

    @BeforeAll
    static void initTableInfo() {
        // 纯 mock 单测无 Spring 上下文：手工初始化 MyBatis-Plus 实体元数据，供 LambdaWrapper 解析列名
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

    static TodoDailyItemDTO tpl(String group, String text, String deadline) {
        TodoDailyItemDTO t = new TodoDailyItemDTO();
        t.setGroup(group);
        t.setText(text);
        t.setDeadline(deadline);
        return t;
    }

    static TodoDailySaveDTO dailySave(String mac, TodoDailyItemDTO... items) {
        TodoDailySaveDTO dto = new TodoDailySaveDTO();
        dto.setMacAddress(mac);
        dto.setItems(List.of(items));
        return dto;
    }

    static TodoDailyTemplateEntity storedTpl(String mac, String group, String text, String deadline, int sort) {
        TodoDailyTemplateEntity e = new TodoDailyTemplateEntity();
        e.setMacAddress(mac);
        e.setGroupKey(group);
        e.setText(text);
        e.setDeadline(deadline);
        e.setSort(sort);
        return e;
    }

    static TodoMirrorEntity storedMirror(String mac, TodoItemDTO... items) {
        TodoMirrorEntity e = new TodoMirrorEntity();
        e.setId("row-1");
        e.setMacAddress(mac);
        e.setItems(xiaozhi.common.utils.JsonUtils.toJsonString(List.of(items)));
        e.setSyncEnabled(1);
        e.setPending(0);
        return e;
    }

    static DeviceEntity ownedDevice() {
        DeviceEntity d = new DeviceEntity();
        d.setUserId(USER_ID);
        return d;
    }

    static TodoServiceImpl newService(TodoMirrorDao mirrorDao, TodoDailyTemplateDao dailyDao,
            DeviceService deviceService) {
        return new TodoServiceImpl(mirrorDao, mock(TodoEventDao.class), deviceService, new TodoOnlineRegistry(),
                dailyDao);
    }

    // ───────────────────────── T3：模板管理（GET/PUT /todo-list/daily） ─────────────────────────

    @Test
    void saveDailyFullReplacesWithSanitizedOrderedRows() {
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(ownedDevice());

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            List<TodoDailyItemDTO> saved = newService(mock(TodoMirrorDao.class), dailyDao, deviceService)
                    .saveDailyForUser(dailySave("AA",
                            tpl("morning", " 刷牙 ", null),
                            tpl("study", "一个超级超级超级超级超级超级超级超级超级超级超级长的任务必须截断", "20:30"), // 32 字
                            tpl("chores", "", null), // 空文本剔除
                            tpl("morning", "刷牙", null))); // 组内同文本去重

            verify(dailyDao).delete(any()); // 全量替换：先清该设备旧模板
            ArgumentCaptor<TodoDailyTemplateEntity> captor = ArgumentCaptor.forClass(TodoDailyTemplateEntity.class);
            verify(dailyDao, org.mockito.Mockito.times(2)).insert(captor.capture());
            List<TodoDailyTemplateEntity> rows = captor.getAllValues();
            assertEquals("AA", rows.get(0).getMacAddress());
            assertEquals("morning", rows.get(0).getGroupKey());
            assertEquals("刷牙", rows.get(0).getText()); // 首尾空格规整
            assertNull(rows.get(0).getDeadline());
            assertEquals(Integer.valueOf(0), rows.get(0).getSort()); // 保存顺序即显示序
            assertEquals("study", rows.get(1).getGroupKey());
            assertEquals(30, rows.get(1).getText().length()); // 单条 30 字截断
            assertEquals("20:30", rows.get(1).getDeadline());
            assertEquals(Integer.valueOf(1), rows.get(1).getSort());
            assertEquals(2, saved.size()); // 返回体与入库一致
            assertEquals("刷牙", saved.get(0).getText());
        }
    }

    @Test
    void saveDailyRejectsUnknownGroupBlankDeadlineInvalidAndOver30Rows() {
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(ownedDevice());

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            TodoServiceImpl service = newService(mock(TodoMirrorDao.class), dailyDao, deviceService);

            RenException badGroup = assertThrows(RenException.class,
                    () -> service.saveDailyForUser(dailySave("AA", tpl("sports", "跑步", null))));
            assertTrue(badGroup.getMsg().contains("分组"), "未知分组应明确拒绝: " + badGroup.getMsg());

            RenException badDeadline = assertThrows(RenException.class,
                    () -> service.saveDailyForUser(dailySave("AA", tpl("study", "写作业", "9:00"))));
            assertTrue(badDeadline.getMsg().contains("截止"), "非法截止时刻应明确拒绝: " + badDeadline.getMsg());

            TodoDailyItemDTO[] tooMany = new TodoDailyItemDTO[31];
            for (int i = 0; i < tooMany.length; i++) {
                tooMany[i] = tpl("study", "任务" + i, null);
            }
            RenException overLimit = assertThrows(RenException.class,
                    () -> service.saveDailyForUser(dailySave("AA", tooMany)));
            assertTrue(overLimit.getMsg().contains("30"), "超 30 条应明确拒绝: " + overLimit.getMsg());

            verify(dailyDao, never()).delete(any()); // 拒绝即不落库
            verify(dailyDao, never()).insert(any(TodoDailyTemplateEntity.class));
        }
    }

    @Test
    void saveDailyRejectsForeignDevice() {
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(new DeviceEntity()); // 无属主

        RenException ex = assertThrows(RenException.class, () -> newService(mock(TodoMirrorDao.class),
                mock(TodoDailyTemplateDao.class), deviceService)
                        .saveDailyForUser(dailySave("AA", tpl("morning", "刷牙", null))));
        assertEquals("设备不存在或无权操作", ex.getMsg());
    }

    @Test
    void saveDailyIsTransactional() throws NoSuchMethodException {
        // H3：delete+insert 全量替换必须原子——中途失败整体回滚，不留空/半模板静默停掉 0 点重建
        assertTrue(TodoServiceImpl.class.getMethod("saveDailyForUser", TodoDailySaveDTO.class)
                .isAnnotationPresent(org.springframework.transaction.annotation.Transactional.class),
                "saveDailyForUser 应有 @Transactional");
    }

    @Test
    void saveDailyRetriesOnceOnConcurrentDuplicateKey() {
        // H3：双击保存/双 tab 并发撞 (mac,group,text) 唯一键 → 重删重插一次，不 500
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(ownedDevice());
        when(dailyDao.insert(any(TodoDailyTemplateEntity.class)))
                .thenThrow(new org.springframework.dao.DuplicateKeyException("uk_todo_daily_mac_group_text"))
                .thenReturn(1);

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            List<TodoDailyItemDTO> saved = newService(mock(TodoMirrorDao.class), dailyDao, deviceService)
                    .saveDailyForUser(dailySave("AA", tpl("morning", "刷牙", null)));

            assertEquals(1, saved.size());
            verify(dailyDao, org.mockito.Mockito.times(2)).delete(any()); // 首插撞唯一键后重删重插
            verify(dailyDao, org.mockito.Mockito.times(2)).insert(any(TodoDailyTemplateEntity.class));
        }
    }

    @Test
    void getDailyReturnsStoredRowsInSortOrderWithOwnerCheck() {
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(ownedDevice());
        when(dailyDao.selectList(any())).thenReturn(List.of(
                storedTpl("AA", "morning", "刷牙", null, 0),
                storedTpl("AA", "study", "写作业", "20:30", 1)));

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            List<TodoDailyItemDTO> daily = newService(mock(TodoMirrorDao.class), dailyDao, deviceService)
                    .getDailyForUser("AA");
            assertEquals(2, daily.size());
            assertEquals("morning", daily.get(0).getGroup());
            assertEquals("刷牙", daily.get(0).getText());
            assertEquals("20:30", daily.get(1).getDeadline());
        }

        when(deviceService.getDeviceByMacAddress("BB")).thenReturn(null);
        assertThrows(RenException.class, () -> newService(mock(TodoMirrorDao.class), dailyDao, deviceService)
                .getDailyForUser("BB"));
    }

    // ───────────────────────── T3：设备级配置随整表保存（#33 评论补充） ─────────────────────────

    @Test
    void saveCarriesDeviceConfigOntoMirror() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(ownedDevice());
        when(mirrorDao.selectOne(any())).thenReturn(storedMirror("AA", item("旧任务", false)));

        TodoReportDTO save = TodoServiceImplTest.report("AA", item("新任务", false));
        save.setSyncEnabled(false);
        save.setQuietStart("22:00");
        save.setQuietEnd("08:00");
        save.setMaxItems(20);

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            newService(mirrorDao, mock(TodoDailyTemplateDao.class), deviceService).saveTodoListForUser(save);

            ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
            verify(mirrorDao).updateById(captor.capture());
            TodoMirrorEntity updated = captor.getValue();
            assertEquals(Integer.valueOf(0), updated.getSyncEnabled()); // 开关关：镜像/事件/下发整体停用
            assertEquals("22:00", updated.getQuietStart());
            assertEquals("08:00", updated.getQuietEnd());
            assertEquals(Integer.valueOf(20), updated.getMaxItems());
        }
    }

    @Test
    void saveRejectsInvalidDeviceConfigWithoutTouchingStorage() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(ownedDevice());

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            TodoServiceImpl service = newService(mirrorDao, mock(TodoDailyTemplateDao.class), deviceService);

            TodoReportDTO badQuiet = TodoServiceImplTest.report("AA", item("刷牙", false));
            badQuiet.setQuietStart("9:00"); // 非 HH:MM
            assertThrows(RenException.class, () -> service.saveTodoListForUser(badQuiet));

            TodoReportDTO badEnd = TodoServiceImplTest.report("AA", item("刷牙", false));
            badEnd.setQuietEnd("24:30"); // 时越界
            assertThrows(RenException.class, () -> service.saveTodoListForUser(badEnd));

            TodoReportDTO badMax = TodoServiceImplTest.report("AA", item("刷牙", false));
            badMax.setMaxItems(31); // 超 30
            assertThrows(RenException.class, () -> service.saveTodoListForUser(badMax));

            verify(mirrorDao, never()).insert(any(TodoMirrorEntity.class));
            verify(mirrorDao, never()).updateById(any(TodoMirrorEntity.class));
        }
    }

    // ───────────────────────── T3：0 点重建语义 ─────────────────────────

    @Test
    void rebuildResetsDailyToUndoneAndKeepsManualItems() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        // 模板：刷牙(morning)、收拾玩具(chores)；镜像：刷牙已完成、写作业未完成(手动)、读绘本已完成(手动)
        when(dailyDao.selectList(any())).thenReturn(List.of(
                storedTpl("AA", "morning", "刷牙", "07:30", 0),
                storedTpl("AA", "chores", "收拾玩具", null, 1)));
        when(mirrorDao.selectOne(any())).thenReturn(storedMirror("AA",
                item("刷牙", true), item("写作业", false), item("读绘本", true)));

        newService(mirrorDao, dailyDao, mock(DeviceService.class)).rebuildDailyLists();

        verify(mirrorDao, never()).insert(any(TodoMirrorEntity.class)); // 已有行只更新
        ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
        verify(mirrorDao).updateById(captor.capture());
        TodoMirrorEntity updated = captor.getValue();
        List<TodoItemDTO> merged = xiaozhi.common.utils.JsonUtils.parseObject(updated.getItems(),
                new com.fasterxml.jackson.core.type.TypeReference<List<TodoItemDTO>>() {
                });
        // 每日项在前（模板顺序、全部重置未完成；#34 模板 deadline 随重建成为当日项 due），手动项在后（镜像顺序、完成状态留存）
        assertEquals(List.of(
                item("刷牙", false, "07:30"), item("收拾玩具", false), item("写作业", false), item("读绘本", true)), merged);
        assertEquals("daily", updated.getSource()); // 重建来源
        assertEquals(Integer.valueOf(1), updated.getPending()); // 经既有 60s 通道送达
    }

    @Test
    void rebuildMatchesDailyByExactTextOnly() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        // 模板文本「刷牙」只匹配镜像同文本项；「睡前刷牙」是不同任务 → 手动留存
        when(dailyDao.selectList(any())).thenReturn(List.of(storedTpl("AA", "morning", "刷牙", null, 0)));
        when(mirrorDao.selectOne(any())).thenReturn(storedMirror("AA",
                item("刷牙", true), item("睡前刷牙", true)));

        newService(mirrorDao, dailyDao, mock(DeviceService.class)).rebuildDailyLists();

        ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
        verify(mirrorDao).updateById(captor.capture());
        List<TodoItemDTO> merged = xiaozhi.common.utils.JsonUtils.parseObject(captor.getValue().getItems(),
                new com.fasterxml.jackson.core.type.TypeReference<List<TodoItemDTO>>() {
                });
        assertEquals(List.of(item("刷牙", false), item("睡前刷牙", true)), merged);
    }

    @Test
    void rebuildTruncatesDailyWhenCapExceededButKeepsAllManual() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        // 设备级上限 3：3 条每日模板 + 2 条手动 → 每日截到 1 条，手动 2 条全保
        TodoMirrorEntity mirror = storedMirror("AA", item("写作业", false), item("读绘本", true));
        mirror.setMaxItems(3);
        when(dailyDao.selectList(any())).thenReturn(List.of(
                storedTpl("AA", "morning", "刷牙", null, 0),
                storedTpl("AA", "study", "背古诗", null, 1),
                storedTpl("AA", "chores", "浇花", null, 2)));
        when(mirrorDao.selectOne(any())).thenReturn(mirror);

        newService(mirrorDao, dailyDao, mock(DeviceService.class)).rebuildDailyLists();

        ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
        verify(mirrorDao).updateById(captor.capture());
        List<TodoItemDTO> merged = xiaozhi.common.utils.JsonUtils.parseObject(captor.getValue().getItems(),
                new com.fasterxml.jackson.core.type.TypeReference<List<TodoItemDTO>>() {
                });
        assertEquals(List.of(item("刷牙", false), item("写作业", false), item("读绘本", true)), merged);
    }

    @Test
    void rebuildSkipsSyncDisabledDeviceAndDeviceWithoutTemplates() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        TodoMirrorEntity syncOff = storedMirror("BB", item("刷牙", true));
        syncOff.setSyncEnabled(0);
        when(dailyDao.selectList(any())).thenReturn(List.of(
                storedTpl("AA", "morning", "刷牙", null, 0),
                storedTpl("BB", "morning", "刷牙", null, 0)));
        when(mirrorDao.selectOne(any())).thenReturn(syncOff); // BB 同步开关关

        newService(mirrorDao, dailyDao, mock(DeviceService.class)).rebuildDailyLists();

        verify(mirrorDao, never()).updateById(any(TodoMirrorEntity.class)); // BB 跳过、无模板设备不进循环
        verify(mirrorDao, never()).insert(any(TodoMirrorEntity.class));
    }

    @Test
    void rebuildCreatesMirrorForDeviceNeverReported() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoDailyTemplateDao dailyDao = mock(TodoDailyTemplateDao.class);
        when(dailyDao.selectList(any())).thenReturn(List.of(storedTpl("AA", "morning", "刷牙", null, 0)));
        when(mirrorDao.selectOne(any())).thenReturn(null); // 从未上报：无镜像行

        newService(mirrorDao, dailyDao, mock(DeviceService.class)).rebuildDailyLists();

        ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
        verify(mirrorDao).insert(captor.capture());
        TodoMirrorEntity inserted = captor.getValue();
        assertEquals(List.of(item("刷牙", false)), xiaozhi.common.utils.JsonUtils.parseObject(inserted.getItems(),
                new com.fasterxml.jackson.core.type.TypeReference<List<TodoItemDTO>>() {
                }));
        assertEquals("daily", inserted.getSource());
        assertEquals(Integer.valueOf(1), inserted.getPending());
    }
}
