package xiaozhi.modules.todo.service.impl;

import java.util.List;

import org.mockito.Mockito;

import com.fasterxml.jackson.core.type.TypeReference;

import xiaozhi.common.utils.JsonUtils;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
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
 * Todo service 三个测试类（Test/DailyTest/DueTest）共用的构造 helper——
 * item/report/parseItems/storedMirror/newService 等此前三处复制，收敛于此（L2）。
 */
final class TodoTestFixtures {

    static final long USER_ID = 42L;

    private static final TypeReference<List<TodoItemDTO>> ITEM_LIST = new TypeReference<>() {
    };

    private TodoTestFixtures() {
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

    static List<TodoItemDTO> parseItems(String json) {
        return JsonUtils.parseObject(json, ITEM_LIST);
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

    /** 归属当前测试用户的设备（配合 MockedStatic SecurityUser） */
    static DeviceEntity ownedDevice() {
        DeviceEntity d = new DeviceEntity();
        d.setUserId(USER_ID);
        return d;
    }

    /** 预置一台已属主设备（mac）的 DeviceService mock */
    static DeviceService ownedDeviceService(String mac) {
        DeviceService deviceService = Mockito.mock(DeviceService.class);
        Mockito.when(deviceService.getDeviceByMacAddress(mac)).thenReturn(ownedDevice());
        return deviceService;
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

    /** 统一构造：服务新增依赖后，老用例不必逐个改构造 */
    static TodoServiceImpl newService(TodoMirrorDao mirrorDao, TodoEventDao eventDao, DeviceService deviceService) {
        return new TodoServiceImpl(mirrorDao, eventDao, deviceService, new TodoOnlineRegistry(),
                Mockito.mock(TodoDailyTemplateDao.class));
    }

    static TodoServiceImpl newService(TodoMirrorDao mirrorDao, TodoEventDao eventDao, DeviceService deviceService,
            TodoOnlineRegistry registry) {
        return new TodoServiceImpl(mirrorDao, eventDao, deviceService, registry,
                Mockito.mock(TodoDailyTemplateDao.class));
    }

    static TodoServiceImpl newService(TodoMirrorDao mirrorDao, TodoDailyTemplateDao dailyDao,
            DeviceService deviceService) {
        return new TodoServiceImpl(mirrorDao, Mockito.mock(TodoEventDao.class), deviceService,
                new TodoOnlineRegistry(), dailyDao);
    }

    static TodoServiceImpl newService(TodoMirrorDao mirrorDao, TodoDailyTemplateDao dailyDao) {
        return newService(mirrorDao, dailyDao, ownedDeviceService("AA"));
    }
}
