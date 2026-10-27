package xiaozhi.modules.todo.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.MockedStatic;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.core.type.TypeReference;

import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.JsonUtils;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.modules.todo.dao.TodoEventDao;
import xiaozhi.modules.todo.dao.TodoMirrorDao;
import xiaozhi.modules.todo.dto.TodoItemDTO;
import xiaozhi.modules.todo.dto.TodoReportDTO;
import xiaozhi.modules.todo.entity.TodoEventEntity;
import xiaozhi.modules.todo.entity.TodoMirrorEntity;
import xiaozhi.modules.todo.service.TodoOnlineRegistry;
import xiaozhi.modules.todo.vo.TodoMirrorVO;

class TodoServiceImplTest {

    private static final long USER_ID = 42L;

    @BeforeAll
    static void initTableInfo() {
        // 纯 mock 单测无 Spring 上下文：手工初始化 MyBatis-Plus 实体元数据，供 LambdaUpdateWrapper 解析列名
        TableInfoHelper.initTableInfo(new org.apache.ibatis.builder.MapperBuilderAssistant(
                new MybatisConfiguration(), ""), TodoMirrorEntity.class);
    }

    private static final TypeReference<List<TodoItemDTO>> ITEM_LIST = new TypeReference<>() {
    };

    static TodoItemDTO item(String text, boolean done) {
        TodoItemDTO i = new TodoItemDTO();
        i.setText(text);
        i.setDone(done);
        return i;
    }

    static TodoReportDTO report(String mac, TodoItemDTO... items) {
        TodoReportDTO dto = new TodoReportDTO();
        dto.setMacAddress(mac);
        dto.setItems(List.of(items));
        return dto;
    }

    static List<TodoItemDTO> parseItems(String json) {
        return JsonUtils.parseObject(json, ITEM_LIST);
    }

    /** 统一构造：服务新增在线注册表依赖后，老用例不必逐个改构造 */
    static TodoServiceImpl newService(TodoMirrorDao mirrorDao, TodoEventDao eventDao, DeviceService deviceService) {
        return new TodoServiceImpl(mirrorDao, eventDao, deviceService, new TodoOnlineRegistry());
    }

    static TodoServiceImpl newService(TodoMirrorDao mirrorDao, TodoEventDao eventDao, DeviceService deviceService,
            TodoOnlineRegistry registry) {
        return new TodoServiceImpl(mirrorDao, eventDao, deviceService, registry);
    }

    /** 归属当前测试用户的设备（配合 MockedStatic SecurityUser） */
    static DeviceEntity ownedDevice() {
        DeviceEntity d = new DeviceEntity();
        d.setUserId(USER_ID);
        return d;
    }

    @Test
    void firstReportInsertsMirrorWithoutEvents() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoEventDao eventDao = mock(TodoEventDao.class);
        when(mirrorDao.selectOne(any())).thenReturn(null);

        newService(mirrorDao, eventDao, mock(DeviceService.class))
                .reportTodoMirror(report("AA", item("读绘本", false), item("刷牙", true)));

        ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
        verify(mirrorDao).insert(captor.capture());
        TodoMirrorEntity e = captor.getValue();
        assertEquals("AA", e.getMacAddress());
        assertEquals(List.of(item("读绘本", false), item("刷牙", true)), parseItems(e.getItems()));
        assertEquals("voice", e.getSource());
        assertNotNull(e.getUpdatedAt());
        verifyNoInteractions(eventDao); // 首报无旧镜像：已完成的「刷牙」不伪造完成事件
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

    @Test
    void reportDiffInsertsCompletionEventOnlyForUndoneToDoneTransition() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoEventDao eventDao = mock(TodoEventDao.class);
        // 旧镜像：读绘本未完成、刷牙已完成、写作业未完成
        when(mirrorDao.selectOne(any()))
                .thenReturn(storedMirror("AA", item("读绘本", false), item("刷牙", true), item("写作业", false)));

        // 新上报：读绘本完成（转变✓）、刷牙仍完成（无转变）、写作业未完成、收拾玩具直接以完成态新增（旧镜像没有，不算转变）
        newService(mirrorDao, eventDao, mock(DeviceService.class))
                .reportTodoMirror(report("AA",
                        item("读绘本", true), item("刷牙", true), item("写作业", false), item("收拾玩具", true)));

        ArgumentCaptor<TodoEventEntity> captor = ArgumentCaptor.forClass(TodoEventEntity.class);
        verify(eventDao).insert(captor.capture());
        TodoEventEntity event = captor.getValue();
        assertEquals("AA", event.getMacAddress());
        assertEquals("读绘本", event.getText());
        assertNotNull(event.getCreatedAt());
    }

    @Test
    void reportOnExistingMirrorUpdatesSameRowInsteadOfInsert() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoEventDao eventDao = mock(TodoEventDao.class);
        TodoMirrorEntity old = storedMirror("AA", item("读绘本", false));
        when(mirrorDao.selectOne(any())).thenReturn(old);

        newService(mirrorDao, eventDao, mock(DeviceService.class))
                .reportTodoMirror(report("AA", item("读绘本", true)));

        verify(mirrorDao, never()).insert(any(TodoMirrorEntity.class)); // mac 唯一：已有行只更新
        ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
        verify(mirrorDao).updateById(captor.capture());
        TodoMirrorEntity updated = captor.getValue();
        assertEquals("row-1", updated.getId());
        assertEquals(List.of(item("读绘本", true)), parseItems(updated.getItems()));
        assertEquals("voice", updated.getSource());
        assertNotNull(updated.getUpdatedAt());
    }

    @Test
    void concurrentFirstReportOnDuplicateKeyFallsBackToUpdate() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoEventDao eventDao = mock(TodoEventDao.class);
        // 首查无行 → insert 撞 mac 唯一键（并发首报）→ 重查拿到既有行 → 走更新
        when(mirrorDao.selectOne(any())).thenReturn(null, storedMirror("AA", item("读绘本", false)));
        doThrow(new org.springframework.dao.DuplicateKeyException("uk_todo_mirror_mac"))
                .when(mirrorDao).insert(any(TodoMirrorEntity.class));

        newService(mirrorDao, eventDao, mock(DeviceService.class))
                .reportTodoMirror(report("AA", item("读绘本", true)));

        verify(mirrorDao).updateById(any(TodoMirrorEntity.class)); // 不丢上报：改走更新
    }

    @Test
    void reportCapsItemsAt30AndTruncatesTextTo30Chars() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoEventDao eventDao = mock(TodoEventDao.class);
        when(mirrorDao.selectOne(any())).thenReturn(null);
        TodoItemDTO[] items = new TodoItemDTO[31];
        for (int i = 0; i < items.length; i++) {
            items[i] = item("任务" + i + "号0123456789012345678901234567890超长部分", false); // 38 字
        }

        newService(mirrorDao, eventDao, mock(DeviceService.class))
                .reportTodoMirror(report("AA", items));

        ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
        verify(mirrorDao).insert(captor.capture());
        List<TodoItemDTO> stored = parseItems(captor.getValue().getItems());
        assertEquals(30, stored.size()); // 软上限 30 条（保序截断，保前 30 条）
        assertTrue(stored.get(29).getText().startsWith("任务29号"),
                "第 30 条应为原始第 30 项（任务29号），实际: " + stored.get(29).getText());
        assertFalse(java.util.Arrays.stream(items).anyMatch(i -> i.getText().length() <= 30)); // 入参确实全部超长
        assertEquals(30, stored.get(0).getText().length()); // 单条 30 字截断
    }

    @Test
    void reportOnSyncDisabledDeviceIsDroppedEntirely() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoEventDao eventDao = mock(TodoEventDao.class);
        TodoMirrorEntity old = storedMirror("AA", item("读绘本", false));
        old.setSyncEnabled(0); // 设备级同步开关关闭
        when(mirrorDao.selectOne(any())).thenReturn(old);

        newService(mirrorDao, eventDao, mock(DeviceService.class))
                .reportTodoMirror(report("AA", item("读绘本", true)));

        verify(mirrorDao, never()).insert(any(TodoMirrorEntity.class));
        verify(mirrorDao, never()).updateById(any(TodoMirrorEntity.class));
        verifyNoInteractions(eventDao); // 开关关：镜像与事件整体跳过
    }

    @Test
    void getMirrorReturnsDefaultsForDeviceNeverReported() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        when(mirrorDao.selectOne(any())).thenReturn(null);

        TodoMirrorVO vo = newService(mirrorDao, mock(TodoEventDao.class), mock(DeviceService.class))
                .getMirror("AA");

        assertEquals("AA", vo.getMac());
        assertEquals(List.of(), vo.getItems());
        assertTrue(vo.isSyncEnabled()); // 默认开
        assertEquals("21:00", vo.getQuietStart()); // 默认静默时段（与表默认一致）
        assertEquals("07:00", vo.getQuietEnd());
        assertEquals(30, vo.getMaxItems());
        assertFalse(vo.isPending());
    }

    @Test
    void getMirrorMapsStoredRow() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoMirrorEntity row = storedMirror("AA", item("读绘本", false));
        row.setSyncEnabled(0);
        row.setPending(1);
        row.setQuietStart("22:00");
        row.setQuietEnd("08:00");
        row.setMaxItems(20);
        row.setSource("voice");
        when(mirrorDao.selectOne(any())).thenReturn(row);

        TodoMirrorVO vo = newService(mirrorDao, mock(TodoEventDao.class), mock(DeviceService.class))
                .getMirror("AA");

        assertEquals("AA", vo.getMac());
        assertEquals(List.of(item("读绘本", false)), vo.getItems());
        assertFalse(vo.isSyncEnabled());
        assertTrue(vo.isPending());
        assertEquals("22:00", vo.getQuietStart());
        assertEquals("08:00", vo.getQuietEnd());
        assertEquals(20, vo.getMaxItems());
    }

    @Test
    void getMirrorForUserRejectsForeignOrMissingDevice() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(null); // 设备不存在
        when(deviceService.getDeviceByMacAddress("BB")).thenReturn(new DeviceEntity()); // 存在但不属于当前用户

        TodoServiceImpl service = newService(mirrorDao, mock(TodoEventDao.class), deviceService);
        RenException ex1 = assertThrows(RenException.class, () -> service.getMirrorForUser("AA"));
        RenException ex2 = assertThrows(RenException.class, () -> service.getMirrorForUser("BB"));
        assertEquals("设备不存在或无权操作", ex1.getMsg());
        assertEquals("设备不存在或无权操作", ex2.getMsg());
    }

    // ───────────────────────── T2：整表保存（PUT /todo-list） ─────────────────────────

    @Test
    void saveRejectsMoreThan30ItemsWithoutTouchingStorage() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(ownedDevice());
        TodoItemDTO[] items = new TodoItemDTO[31];
        for (int i = 0; i < items.length; i++) {
            items[i] = item("任务" + i, false);
        }

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            RenException ex = assertThrows(RenException.class, () -> newService(mirrorDao, mock(TodoEventDao.class),
                    deviceService).saveTodoListForUser(report("AA", items)));

            assertTrue(ex.getMsg().contains("30"), "提示应含上限 30，实际: " + ex.getMsg());
        }
        verify(mirrorDao, never()).insert(any(TodoMirrorEntity.class)); // 拒绝即不落库
        verify(mirrorDao, never()).updateById(any(TodoMirrorEntity.class));
    }

    @Test
    void saveInsertsNewMirrorTruncatesTextSetsPendingAdminSource() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(ownedDevice());
        TodoMirrorEntity saved = storedMirror("AA", item("读绘本", false));
        saved.setPending(1); // 保存写库后的重读（返回体供页面立即显示徽标）
        when(mirrorDao.selectOne(any())).thenReturn(null, saved);

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            TodoMirrorVO vo = newService(mirrorDao, mock(TodoEventDao.class), deviceService)
                    .saveTodoListForUser(report("AA",
                            item("读绘本", false),
                            item("一个超级超级超级超级超级超级超级超级超级长任务文本必须被截断", true))); // 38 字

            ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
            verify(mirrorDao).insert(captor.capture());
            TodoMirrorEntity e = captor.getValue();
            assertEquals("AA", e.getMacAddress());
            assertEquals(2, parseItems(e.getItems()).size());
            assertEquals(30, parseItems(e.getItems()).get(1).getText().length()); // 单条 30 字截断
            assertEquals(Integer.valueOf(1), e.getPending()); // 保存即置待下发
            assertEquals("admin", e.getSource());
            assertTrue(vo.isPending());
        }
    }

    @Test
    void saveUpdatesExistingMirrorSetsPending() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(ownedDevice());
        when(mirrorDao.selectOne(any())).thenReturn(storedMirror("AA", item("旧任务", false)));

        try (MockedStatic<SecurityUser> su = mockStatic(SecurityUser.class)) {
            su.when(SecurityUser::getUserId).thenReturn(USER_ID);
            newService(mirrorDao, mock(TodoEventDao.class), deviceService)
                    .saveTodoListForUser(report("AA", item("新任务", false)));

            verify(mirrorDao, never()).insert(any(TodoMirrorEntity.class)); // mac 唯一：已有行只更新
            ArgumentCaptor<TodoMirrorEntity> captor = ArgumentCaptor.forClass(TodoMirrorEntity.class);
            verify(mirrorDao).updateById(captor.capture());
            assertEquals("row-1", captor.getValue().getId());
            assertEquals(Integer.valueOf(1), captor.getValue().getPending());
            assertEquals("admin", captor.getValue().getSource());
            assertEquals(List.of(item("新任务", false)), parseItems(captor.getValue().getItems()));
        }
    }

    @Test
    void saveRejectsForeignDevice() {
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("AA")).thenReturn(new DeviceEntity()); // 无属主

        RenException ex = assertThrows(RenException.class, () -> newService(mock(TodoMirrorDao.class),
                mock(TodoEventDao.class), deviceService).saveTodoListForUser(report("AA", item("读绘本", false))));
        assertEquals("设备不存在或无权操作", ex.getMsg());
    }

    // ───────────────────────── T2：下发闭环（pending 拉取 / 送达回执） ─────────────────────────

    @Test
    void getPendingMirrorsReturnsOnlyPendingAndSyncEnabledRows() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        TodoMirrorEntity pendingOn = storedMirror("AA", item("读绘本", false));
        pendingOn.setPending(1);
        TodoMirrorEntity syncOff = storedMirror("BB", item("写作业", false));
        syncOff.setPending(1);
        syncOff.setSyncEnabled(0); // 同步开关关：循环不下发
        TodoMirrorEntity notPending = storedMirror("CC", item("刷牙", false));
        when(mirrorDao.selectList(any())).thenReturn(List.of(pendingOn, syncOff, notPending));

        List<TodoMirrorVO> pending = newService(mirrorDao, mock(TodoEventDao.class), mock(DeviceService.class))
                .getPendingMirrors();

        assertEquals(1, pending.size());
        assertEquals("AA", pending.get(0).getMac());
        assertEquals(List.of(item("读绘本", false)), pending.get(0).getItems());
    }

    @Test
    void markDeliveredClearsPendingOnlyWhenItemsUnchanged() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        when(mirrorDao.update(any(), any())).thenReturn(1); // 条件命中（镜像内容==送达内容）→ pending 清

        newService(mirrorDao, mock(TodoEventDao.class), mock(DeviceService.class))
                .markDelivered(report("AA", item("读绘本", false)));

        org.mockito.Mockito.verify(mirrorDao, org.mockito.Mockito.times(1)).update(any(), any());

        // 家长在送达期间又保存新清单：镜像 items 已变 → 条件不命中（0 行）→ pending 保留待下一轮下发
        when(mirrorDao.update(any(), any())).thenReturn(0);
        newService(mirrorDao, mock(TodoEventDao.class), mock(DeviceService.class))
                .markDelivered(report("AA", item("读绘本", false)));
        org.mockito.Mockito.verify(mirrorDao, org.mockito.Mockito.times(2)).update(any(), any());
    }

    // ───────────────────────── T2：在线状态（xiaozhi-server 周期上报） ─────────────────────────

    @Test
    void onlineRegistryReportsAndExpires() {
        TodoOnlineRegistry registry = new TodoOnlineRegistry();
        AtomicLong now = new AtomicLong(1_000_000L);
        registry.setClock(now::get);

        assertFalse(registry.isOnline("AA")); // 未上报过
        registry.reportOnline(List.of("AA", "BB"));
        assertTrue(registry.isOnline("AA"));
        assertTrue(registry.isOnline("BB"));
        registry.reportOnline(List.of("AA")); // 新一轮只报 AA
        assertFalse(registry.isOnline("BB")); // 上一轮的 BB 未续报即离线
        now.addAndGet(TodoOnlineRegistry.TTL_MILLIS + 1);
        assertFalse(registry.isOnline("AA")); // 超过 TTL 未续报即离线（xiaozhi-server 重启兜底）
    }

    @Test
    void getMirrorCarriesDeviceOnline() {
        TodoMirrorDao mirrorDao = mock(TodoMirrorDao.class);
        when(mirrorDao.selectOne(any())).thenReturn(storedMirror("AA", item("读绘本", false)));
        TodoOnlineRegistry registry = new TodoOnlineRegistry();
        registry.reportOnline(List.of("AA"));

        TodoMirrorVO vo = newService(mirrorDao, mock(TodoEventDao.class), mock(DeviceService.class), registry)
                .getMirror("AA");
        assertTrue(vo.isDeviceOnline());

        when(mirrorDao.selectOne(any())).thenReturn(null); // 未上报设备
        assertFalse(newService(mirrorDao, mock(TodoEventDao.class), mock(DeviceService.class), registry)
                .getMirror("ZZ").isDeviceOnline());
    }
}
