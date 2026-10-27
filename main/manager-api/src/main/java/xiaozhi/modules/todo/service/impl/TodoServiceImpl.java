package xiaozhi.modules.todo.service.impl;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.core.type.TypeReference;

import lombok.AllArgsConstructor;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.JsonUtils;
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
import xiaozhi.modules.todo.entity.TodoEventEntity;
import xiaozhi.modules.todo.entity.TodoMirrorEntity;
import xiaozhi.modules.todo.service.TodoOnlineRegistry;
import xiaozhi.modules.todo.service.TodoService;
import xiaozhi.modules.todo.vo.TodoMirrorVO;

@Service
@AllArgsConstructor
public class TodoServiceImpl implements TodoService {

    /** 设备契约：item 结构 {"text","done"}，软上限 30 条 / 30 字（NVS 单键 ~4KB 物理边界之内） */
    static final int MAX_ITEMS = 30;
    static final int MAX_TEXT_LEN = 30;
    static final String SOURCE_VOICE = "voice";
    static final String SOURCE_ADMIN = "admin";
    static final String DEFAULT_QUIET_START = "21:00";
    static final String DEFAULT_QUIET_END = "07:00";

    private static final TypeReference<List<TodoItemDTO>> ITEM_LIST = new TypeReference<>() {
    };

    private final TodoMirrorDao mirrorDao;
    private final TodoEventDao eventDao;
    private final DeviceService deviceService;
    private final TodoOnlineRegistry onlineRegistry;
    private final TodoDailyTemplateDao dailyDao;

    @Override
    public void reportTodoMirror(TodoReportDTO dto) {
        List<TodoItemDTO> items = normalize(dto.getItems());
        TodoMirrorEntity existing = selectByMac(dto.getMacAddress());
        if (existing != null && Integer.valueOf(0).equals(existing.getSyncEnabled())) {
            return; // 设备级同步开关关闭：镜像与完成事件整体跳过（写边界单点执法）
        }

        Date now = new Date();
        if (existing != null) {
            // 完成事件：与旧镜像 diff 出「由未完成变为完成」的转变（首报 existing==null 不产生事件）
            insertCompletionEvents(dto.getMacAddress(), parseItems(existing.getItems()), items, now);
        }
        // 设备级配置列与 pending 不在语音上报的写集内：pending 传 null，updateById 已加载值原样写回
        writeMirror(dto.getMacAddress(), items, SOURCE_VOICE, null, null, existing, null);
    }

    @Override
    public TodoMirrorVO saveTodoListForUser(TodoReportDTO dto) {
        requireOwnedDevice(dto.getMacAddress());
        if (dto.getItems() != null && dto.getItems().size() > MAX_ITEMS) {
            throw new RenException("清单最多 " + MAX_ITEMS + " 条（当前 " + dto.getItems().size()
                    + " 条），与设备存储上限一致，请先删减任务");
        }
        validateDeviceConfig(dto);
        List<TodoItemDTO> items = sanitize(dto.getItems()); // 单条 30 字截断；条数超限已整体拒绝，不再裁剪
        writeMirror(dto.getMacAddress(), items, SOURCE_ADMIN, 1, SecurityUser.getUserId(),
                selectByMac(dto.getMacAddress()), dto);
        return getMirror(dto.getMacAddress());
    }

    /** 设备级配置信任边界校验（#33 评论补充）：静默时刻必须 HH:MM、上限 1-30；字段缺省/空白=不修改 */
    private static void validateDeviceConfig(TodoReportDTO dto) {
        String quietStart = StringUtils.trimToNull(dto.getQuietStart());
        if (quietStart != null && !HH_MM.matcher(quietStart).matches()) {
            throw new RenException("静默起始时刻格式应为 HH:MM，如 21:00");
        }
        String quietEnd = StringUtils.trimToNull(dto.getQuietEnd());
        if (quietEnd != null && !HH_MM.matcher(quietEnd).matches()) {
            throw new RenException("静默结束时刻格式应为 HH:MM，如 07:00");
        }
        if (dto.getMaxItems() != null && (dto.getMaxItems() < 1 || dto.getMaxItems() > MAX_ITEMS)) {
            throw new RenException("清单条数上限应在 1-" + MAX_ITEMS + " 之间");
        }
    }

    /** 配置补丁落实体：null 字段不动已加载值/表默认值（不可变风格——只写显式给出的字段） */
    private static void applyDeviceConfig(TodoMirrorEntity entity, TodoReportDTO patch) {
        if (patch == null) {
            return;
        }
        if (patch.getSyncEnabled() != null) {
            entity.setSyncEnabled(patch.getSyncEnabled() ? 1 : 0);
        }
        if (StringUtils.trimToNull(patch.getQuietStart()) != null) {
            entity.setQuietStart(patch.getQuietStart().trim());
        }
        if (StringUtils.trimToNull(patch.getQuietEnd()) != null) {
            entity.setQuietEnd(patch.getQuietEnd().trim());
        }
        if (patch.getMaxItems() != null) {
            entity.setMaxItems(patch.getMaxItems());
        }
    }

    @Override
    public List<TodoMirrorVO> getPendingMirrors() {
        // 一行一设备的小表，全量拉取内存过滤即可（ponytail：真到万级设备再下推 SQL 条件）
        List<TodoMirrorEntity> rows = mirrorDao.selectList(null);
        return rows.stream()
                .filter(r -> Integer.valueOf(1).equals(r.getPending()))
                .filter(r -> !Integer.valueOf(0).equals(r.getSyncEnabled())) // 同步开关关：不下发
                .map(r -> {
                    TodoMirrorVO vo = new TodoMirrorVO();
                    vo.setMac(r.getMacAddress());
                    vo.setItems(parseItems(r.getItems()));
                    return vo;
                })
                .collect(Collectors.toList());
    }

    @Override
    public void markDelivered(TodoReportDTO dto) {
        // 条件更新原子表达「内容未变才清 pending」：家长在送达期间又保存了新清单时，
        // items 已变 → 0 行命中 → 新 pending 保留，下一轮循环照常下发
        mirrorDao.update(null, new LambdaUpdateWrapper<TodoMirrorEntity>()
                .eq(TodoMirrorEntity::getMacAddress, dto.getMacAddress())
                .eq(TodoMirrorEntity::getItems, JsonUtils.toJsonString(sanitize(dto.getItems())))
                .set(TodoMirrorEntity::getPending, 0));
    }

    /** 镜像写单点：insert（撞 mac 唯一键回退更新）/ update；pending 传 null 表示不改写已加载值；
     *  configPatch 非空时设备级配置列一并写入（家长整表保存路径），null 表示不动 */
    private void writeMirror(String macAddress, List<TodoItemDTO> items, String source, Integer pending, Long updater,
            TodoMirrorEntity existing, TodoReportDTO configPatch) {
        Date now = new Date();
        String json = JsonUtils.toJsonString(items);
        if (existing == null) {
            TodoMirrorEntity entity = new TodoMirrorEntity();
            entity.setMacAddress(macAddress);
            entity.setItems(json);
            entity.setSource(source);
            entity.setPending(pending);
            entity.setUpdater(updater);
            entity.setCreatedAt(now);
            entity.setUpdatedAt(now);
            applyDeviceConfig(entity, configPatch);
            try {
                mirrorDao.insert(entity);
                return;
            } catch (org.springframework.dao.DuplicateKeyException e) {
                // 并发首写撞 mac 唯一键：重查改为更新（照 mathPractice saveConfig 先例）
                existing = selectByMac(macAddress);
                if (existing == null) {
                    throw new RenException("todo 镜像保存失败: " + e.getMessage());
                }
            }
        }
        applyDeviceConfig(existing, configPatch);
        existing.setItems(json);
        existing.setSource(source);
        if (pending != null) {
            existing.setPending(pending);
        }
        existing.setUpdater(updater);
        existing.setUpdatedAt(now);
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
        vo.setDeviceOnline(onlineRegistry.isOnline(macAddress));
        vo.setSource(entity == null ? null : entity.getSource());
        vo.setUpdatedAt(entity == null ? null : entity.getUpdatedAt());
        return vo;
    }

    @Override
    public TodoMirrorVO getMirrorForUser(String macAddress) {
        requireOwnedDevice(macAddress);
        return getMirror(macAddress);
    }

    // ───────────────────────── T3：每日任务（模板管理 + 0 点重建） ─────────────────────────

    /** 四组固定（与家长页/原型一致），与 web TEMPLATE_KEYS 保持同步 */
    private static final Set<String> DAILY_GROUPS = Set.of("morning", "study", "chores", "bedtime");
    private static final String SOURCE_DAILY = "daily";
    private static final Pattern HH_MM = Pattern.compile("^([01]\\d|2[0-3]):[0-5]\\d$");

    @Override
    public List<TodoDailyItemDTO> getDailyForUser(String macAddress) {
        requireOwnedDevice(macAddress);
        return selectDaily(macAddress).stream().map(TodoServiceImpl::toDailyItem).collect(Collectors.toList());
    }

    @Override
    public List<TodoDailyItemDTO> saveDailyForUser(TodoDailySaveDTO dto) {
        requireOwnedDevice(dto.getMacAddress());
        // 信任边界规整：空行静默剔除、30 字截断、(组,文本)去重保首；非法分组/截止时刻明确拒绝
        List<TodoDailyItemDTO> cleaned = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (TodoDailyItemDTO t : dto.getItems() == null ? List.<TodoDailyItemDTO>of() : dto.getItems()) {
            if (t == null || StringUtils.isBlank(t.getText())) {
                continue; // 家长页未填完的空行
            }
            if (!DAILY_GROUPS.contains(t.getGroup())) {
                throw new RenException("每日任务分组不合法（仅支持晨间/学习/家务/睡前）");
            }
            String deadline = StringUtils.trimToNull(t.getDeadline());
            if (deadline != null && !HH_MM.matcher(deadline).matches()) {
                throw new RenException("截止时刻格式应为 HH:MM，如 20:30");
            }
            String text = StringUtils.substring(StringUtils.trim(t.getText()), 0, MAX_TEXT_LEN);
            if (seen.add(t.getGroup() + "\u0000" + text)) { // (组,文本)去重保首；不改入参，组装新对象
                TodoDailyItemDTO c = new TodoDailyItemDTO();
                c.setGroup(t.getGroup());
                c.setText(text);
                c.setDeadline(deadline);
                cleaned.add(c);
            }
        }
        if (cleaned.size() > MAX_ITEMS) {
            throw new RenException("每日任务最多 " + MAX_ITEMS + " 条（当前 " + cleaned.size() + " 条）");
        }
        Date now = new Date();
        Long userId = SecurityUser.getUserId();
        dailyDao.delete(new LambdaQueryWrapper<TodoDailyTemplateEntity>()
                .eq(TodoDailyTemplateEntity::getMacAddress, dto.getMacAddress())); // 全量替换
        List<TodoDailyItemDTO> saved = new ArrayList<>(cleaned.size());
        for (int i = 0; i < cleaned.size(); i++) {
            TodoDailyItemDTO c = cleaned.get(i);
            TodoDailyTemplateEntity row = new TodoDailyTemplateEntity();
            row.setMacAddress(dto.getMacAddress());
            row.setGroupKey(c.getGroup());
            row.setText(c.getText());
            row.setDeadline(c.getDeadline());
            row.setSort(i); // 保存顺序即显示序与重建顺序
            row.setCreator(userId);
            row.setCreatedAt(now);
            dailyDao.insert(row);
            saved.add(c);
        }
        return saved;
    }

    @Override
    public void rebuildDailyLists() {
        // 一趟全表按显示序取回再按 mac 分组：每台设备的模板保持保存顺序（无模板的设备天然不进循环）
        Map<String, List<TodoDailyTemplateEntity>> byMac = new LinkedHashMap<>();
        for (TodoDailyTemplateEntity row : dailyDao.selectList(new LambdaQueryWrapper<TodoDailyTemplateEntity>()
                .orderByAsc(TodoDailyTemplateEntity::getSort))) {
            byMac.computeIfAbsent(row.getMacAddress(), k -> new ArrayList<>()).add(row);
        }
        for (Map.Entry<String, List<TodoDailyTemplateEntity>> entry : byMac.entrySet()) {
            String mac = entry.getKey();
            TodoMirrorEntity mirror = selectByMac(mac);
            if (mirror != null && Integer.valueOf(0).equals(mirror.getSyncEnabled())) {
                continue; // 设备级同步开关关：不重建不下发
            }
            writeMirror(mac, mergeDaily(entry.getValue(), mirror), SOURCE_DAILY, 1, null, mirror, null);
        }
    }

    /** 当日清单 = 每日模板项（全部重置未完成、模板顺序、同文本去重保首）∪ 镜像中非每日项（完成与否都留存、镜像顺序）。
     *  合并超设备级上限时截每日项保手动项（拒绝重建会让昨日清单永远残留，截断更安全）。 */
    private static List<TodoItemDTO> mergeDaily(List<TodoDailyTemplateEntity> templates, TodoMirrorEntity mirror) {
        List<TodoItemDTO> daily = new ArrayList<>();
        Set<String> dailyTexts = new HashSet<>();
        for (TodoDailyTemplateEntity t : templates) {
            if (dailyTexts.add(t.getText())) {
                daily.add(itemOf(t.getText(), false));
            }
        }
        List<TodoItemDTO> manual = parseItems(mirror == null ? null : mirror.getItems()).stream()
                .filter(i -> !dailyTexts.contains(i.getText()))
                .collect(Collectors.toList());
        int cap = mirror != null && mirror.getMaxItems() != null && mirror.getMaxItems() > 0 ? mirror.getMaxItems()
                : MAX_ITEMS;
        if (daily.size() + manual.size() > cap) {
            daily = daily.subList(0, Math.max(0, cap - manual.size()));
        }
        List<TodoItemDTO> merged = new ArrayList<>(daily.size() + manual.size());
        merged.addAll(daily);
        merged.addAll(manual);
        return merged;
    }

    private static TodoItemDTO itemOf(String text, boolean done) {
        TodoItemDTO i = new TodoItemDTO();
        i.setText(text);
        i.setDone(done);
        return i;
    }

    private List<TodoDailyTemplateEntity> selectDaily(String macAddress) {
        return dailyDao.selectList(new LambdaQueryWrapper<TodoDailyTemplateEntity>()
                .eq(TodoDailyTemplateEntity::getMacAddress, macAddress)
                .orderByAsc(TodoDailyTemplateEntity::getSort));
    }

    private static TodoDailyItemDTO toDailyItem(TodoDailyTemplateEntity row) {
        TodoDailyItemDTO dto = new TodoDailyItemDTO();
        dto.setGroup(row.getGroupKey());
        dto.setText(row.getText());
        dto.setDeadline(row.getDeadline());
        return dto;
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

    /** 信任边界规整：单条文本 30 字截断；产出新对象不改入参（条数上限由调用方决定拒绝或截断） */
    private static List<TodoItemDTO> sanitize(List<TodoItemDTO> items) {
        if (items == null) {
            return Collections.emptyList();
        }
        return items.stream().map(i -> {
            TodoItemDTO t = new TodoItemDTO();
            t.setText(StringUtils.substring(StringUtils.defaultString(i.getText()), 0, MAX_TEXT_LEN));
            t.setDone(Boolean.TRUE.equals(i.getDone()));
            return t;
        }).collect(Collectors.toList());
    }

    /** 上报路径规整：sanitize 基础上再保序截断到 30 条（设备侧软上限，语音路径无拒绝语义） */
    private static List<TodoItemDTO> normalize(List<TodoItemDTO> items) {
        return sanitize(items).stream().limit(MAX_ITEMS).collect(Collectors.toList());
    }
}

