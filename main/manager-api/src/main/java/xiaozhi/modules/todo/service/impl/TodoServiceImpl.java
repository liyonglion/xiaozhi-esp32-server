package xiaozhi.modules.todo.service.impl;

import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;

import lombok.AllArgsConstructor;
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
import xiaozhi.modules.todo.service.TodoService;
import xiaozhi.modules.todo.vo.TodoMirrorVO;

@Service
@AllArgsConstructor
public class TodoServiceImpl implements TodoService {

    /** 设备契约：item 结构 {"text","done"}，软上限 30 条 / 30 字（NVS 单键 ~4KB 物理边界之内） */
    static final int MAX_ITEMS = 30;
    static final int MAX_TEXT_LEN = 30;
    static final String SOURCE_VOICE = "voice";
    static final String DEFAULT_QUIET_START = "21:00";
    static final String DEFAULT_QUIET_END = "07:00";

    private static final TypeReference<List<TodoItemDTO>> ITEM_LIST = new TypeReference<>() {
    };

    private final TodoMirrorDao mirrorDao;
    private final TodoEventDao eventDao;
    private final DeviceService deviceService;

    @Override
    public void reportTodoMirror(TodoReportDTO dto) {
        List<TodoItemDTO> items = normalize(dto.getItems());
        TodoMirrorEntity existing = selectByMac(dto.getMacAddress());
        if (existing != null && Integer.valueOf(0).equals(existing.getSyncEnabled())) {
            return; // 设备级同步开关关闭：镜像与完成事件整体跳过（写边界单点执法）
        }

        Date now = new Date();
        if (existing == null) {
            TodoMirrorEntity entity = new TodoMirrorEntity();
            entity.setMacAddress(dto.getMacAddress());
            entity.setItems(JsonUtils.toJsonString(items));
            entity.setSource(SOURCE_VOICE);
            entity.setCreatedAt(now);
            entity.setUpdatedAt(now);
            try {
                mirrorDao.insert(entity);
                return;
            } catch (org.springframework.dao.DuplicateKeyException e) {
                // 并发首报撞 mac 唯一键：重查改为更新（照 mathPractice saveConfig 先例）
                existing = selectByMac(dto.getMacAddress());
                if (existing == null) {
                    throw new RenException("todo 镜像保存失败: " + e.getMessage());
                }
            }
        }

        // 完成事件：与旧镜像 diff 出「由未完成变为完成」的转变（首报 existing==null 不产生事件）
        insertCompletionEvents(dto.getMacAddress(), parseItems(existing.getItems()), items, now);

        existing.setItems(JsonUtils.toJsonString(items));
        existing.setSource(SOURCE_VOICE);
        existing.setUpdatedAt(now);
        // 设备级配置列与 pending 不在语音上报的写集内：updateById 忽略 null，已加载值原样写回
        mirrorDao.updateById(existing);
    }

    @Override
    public TodoMirrorVO getMirror(String macAddress) {
        TodoMirrorEntity entity = selectByMac(macAddress);
        TodoMirrorVO vo = new TodoMirrorVO();
        vo.setMac(macAddress);
        vo.setItems(parseItems(entity == null ? null : entity.getItems()));
        vo.setSyncEnabled(entity == null || !Integer.valueOf(0).equals(entity.getSyncEnabled()));
        vo.setQuietStart(entity != null && entity.getQuietStart() != null ? entity.getQuietStart() : DEFAULT_QUIET_START);
        vo.setQuietEnd(entity != null && entity.getQuietEnd() != null ? entity.getQuietEnd() : DEFAULT_QUIET_END);
        vo.setMaxItems(entity != null && entity.getMaxItems() != null ? entity.getMaxItems() : MAX_ITEMS);
        vo.setPending(entity != null && Integer.valueOf(1).equals(entity.getPending()));
        vo.setSource(entity == null ? null : entity.getSource());
        vo.setUpdatedAt(entity == null ? null : entity.getUpdatedAt());
        return vo;
    }

    @Override
    public TodoMirrorVO getMirrorForUser(String macAddress) {
        requireOwnedDevice(macAddress);
        return getMirror(macAddress);
    }

    /** 完成事件 diff：新清单中 done 且旧清单中同文本未完成的项，逐条入库 */
    private void insertCompletionEvents(String macAddress, List<TodoItemDTO> oldItems,
            List<TodoItemDTO> newItems, Date now) {
        if (oldItems == null || oldItems.isEmpty()) {
            return;
        }
        Set<String> oldUndoneTexts = oldItems.stream()
                .filter(i -> !Boolean.TRUE.equals(i.getDone()))
                .map(TodoItemDTO::getText)
                .collect(Collectors.toSet());
        for (TodoItemDTO item : newItems) {
            if (Boolean.TRUE.equals(item.getDone()) && oldUndoneTexts.contains(item.getText())) {
                TodoEventEntity event = new TodoEventEntity();
                event.setMacAddress(macAddress);
                event.setText(item.getText());
                event.setCreatedAt(now);
                eventDao.insert(event);
            }
        }
    }

    /** 镜像 JSON → 清单；行内 JSON 由本服务写入，个别脏行不应让家长查询 500，回落空表待下次上报覆盖 */
    private static List<TodoItemDTO> parseItems(String json) {
        if (StringUtils.isBlank(json)) {
            return Collections.emptyList();
        }
        try {
            List<TodoItemDTO> items = JsonUtils.parseObject(json, ITEM_LIST);
            return items == null ? Collections.emptyList() : items;
        } catch (Exception e) {
            return Collections.emptyList();
        }
    }

    private TodoMirrorEntity selectByMac(String macAddress) {
        return mirrorDao.selectOne(new LambdaQueryWrapper<TodoMirrorEntity>()
                .eq(TodoMirrorEntity::getMacAddress, macAddress));
    }

    /** 设备必须存在且属于当前用户（家长只能查自己的设备） */
    private void requireOwnedDevice(String macAddress) {
        DeviceEntity device = deviceService.getDeviceByMacAddress(macAddress);
        if (device == null || device.getUserId() == null || !device.getUserId().equals(SecurityUser.getUserId())) {
            throw new RenException("设备不存在或无权操作");
        }
    }

    /** 信任边界规整：软上限 30 条（保序截断）、单条文本 30 字截断；产出新对象不改入参 */
    private static List<TodoItemDTO> normalize(List<TodoItemDTO> items) {
        if (items == null) {
            return Collections.emptyList();
        }
        return items.stream().limit(MAX_ITEMS).map(i -> {
            TodoItemDTO t = new TodoItemDTO();
            t.setText(StringUtils.substring(StringUtils.defaultString(i.getText()), 0, MAX_TEXT_LEN));
            t.setDone(Boolean.TRUE.equals(i.getDone()));
            return t;
        }).collect(Collectors.toList());
    }
}

