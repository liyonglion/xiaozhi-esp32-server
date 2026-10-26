package xiaozhi.modules.mathpractice.service.impl;

import java.text.SimpleDateFormat;
import java.time.ZoneId;
import java.util.Arrays;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;

import lombok.AllArgsConstructor;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.page.PageData;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.mathpractice.dao.MathPracticeConfigDao;
import xiaozhi.modules.mathpractice.dao.MathPracticeRecordDao;
import xiaozhi.modules.mathpractice.dto.MathPracticeConfigSaveDTO;
import xiaozhi.modules.mathpractice.dto.MathPracticeReportDTO;
import xiaozhi.modules.mathpractice.entity.MathPracticeConfigEntity;
import xiaozhi.modules.mathpractice.entity.MathPracticeRecordEntity;
import xiaozhi.modules.mathpractice.service.MathPracticeService;
import xiaozhi.modules.mathpractice.vo.MathPracticeConfigVO;
import xiaozhi.modules.mathpractice.vo.MathPracticeProgressVO;
import xiaozhi.modules.security.user.SecurityUser;

@Service
@AllArgsConstructor
public class MathPracticeServiceImpl implements MathPracticeService {

    /** 年级预设合法值（与 xiaozhi-server generator.PRESETS 保持同步） */
    private static final Set<String> VALID_PRESETS = Set.of("preschool", "g1a", "g1b", "g2a", "g2b");

    /** 题型 ID 合法值（与 xiaozhi-server generator.TYPES 保持同步） */
    private static final Set<String> VALID_TYPE_IDS = Set.of(
            "A1", "A2", "A3", "A4", "A5", "A6", "A7",
            "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8",
            "M1", "M2", "M3", "D1", "D2",
            "CMP5", "CMP10", "CMP100", "ADJ100", "PAT20", "DEC");

    private static final int DEFAULT_QUESTION_COUNT = 10;

    private final MathPracticeConfigDao configDao;
    private final MathPracticeRecordDao recordDao;
    private final DeviceService deviceService;

    @Override
    public MathPracticeConfigVO getConfigByMac(String macAddress) {
        MathPracticeConfigEntity entity = selectByMac(macAddress);
        // 未配置也返回体（#29）：streakEnd 续接值随本接口捎回零新请求；
        // preset 等字段为空由 python 侧回落默认档（#24 决议不变）
        MathPracticeConfigVO vo = entity == null ? new MathPracticeConfigVO() : toVO(entity);
        if (entity == null) {
            vo.setMacAddress(macAddress);
        }
        vo.setStreakEnd(latestStreakEnd(macAddress));
        return vo;
    }

    @Override
    public MathPracticeConfigVO getConfigForUser(String macAddress) {
        requireOwnedDevice(macAddress);
        return getConfigByMac(macAddress);
    }

    @Override
    public MathPracticeConfigVO saveConfig(MathPracticeConfigSaveDTO dto) {
        validate(dto);
        requireOwnedDevice(dto.getMacAddress());

        Date now = new Date();
        Long userId = SecurityUser.getUserId();
        MathPracticeConfigEntity entity = selectByMac(dto.getMacAddress());
        if (entity == null) {
            entity = new MathPracticeConfigEntity();
            entity.setMacAddress(dto.getMacAddress());
            entity.setCreator(userId);
            entity.setCreatedAt(now);
        }
        entity.setPreset(dto.getPreset());
        entity.setTypeIds(joinTypeIds(dto.getTypeIds()));
        entity.setQuestionCount(dto.getQuestionCount() != null ? dto.getQuestionCount() : DEFAULT_QUESTION_COUNT);
        entity.setUpdater(userId);
        entity.setUpdatedAt(now);
        if (entity.getId() == null) {
            try {
                configDao.insert(entity);
            } catch (org.springframework.dao.DuplicateKeyException e) {
                // 并发首次保存撞 mac 唯一键：重查改为更新
                MathPracticeConfigEntity existing = selectByMac(dto.getMacAddress());
                entity.setId(existing.getId());
                entity.setCreator(existing.getCreator());
                entity.setCreatedAt(existing.getCreatedAt());
                updateAllFields(entity);
            }
        } else {
            updateAllFields(entity);
        }
        return toVO(entity);
    }

    @Override
    public void reportRecord(MathPracticeReportDTO dto) {
        MathPracticeRecordEntity entity = new MathPracticeRecordEntity();
        entity.setMacAddress(dto.getMacAddress());
        entity.setPreset(dto.getPreset());
        entity.setTotal(dto.getTotal());
        entity.setCorrect(dto.getCorrect());
        entity.setDurationSeconds(dto.getDurationSeconds());
        entity.setStreakEnd(dto.getStreakEnd());
        entity.setStreakPeak(dto.getStreakPeak());
        entity.setCreatedAt(new Date());
        recordDao.insert(entity);
    }

    @Override
    public MathPracticeProgressVO getProgress(String macAddress) {
        // 今日=自然日、周=7 天滚动（含今日），口径依服务器时区（部署为 UTC+8，#29）
        ZoneId zone = ZoneId.systemDefault();
        Date todayStart = Date.from(java.time.LocalDate.now(zone).atStartOfDay(zone).toInstant());
        Date weekStart = Date.from(java.time.LocalDate.now(zone).minusDays(6).atStartOfDay(zone).toInstant());

        // 近 7 天整段拉回内存聚合：设备=单孩子，会话量级每天个位数，行数天然有界
        List<MathPracticeRecordEntity> week = recordDao.selectList(
                new LambdaQueryWrapper<MathPracticeRecordEntity>()
                        .eq(MathPracticeRecordEntity::getMacAddress, macAddress)
                        .ge(MathPracticeRecordEntity::getCreatedAt, weekStart));
        int weekCorrect = 0, weekTotal = 0, todayCorrect = 0, todayTotal = 0, todayMaxStreak = 0;
        for (MathPracticeRecordEntity e : week) {
            weekCorrect += nvl(e.getCorrect());
            weekTotal += nvl(e.getTotal());
            if (e.getCreatedAt() != null && !e.getCreatedAt().before(todayStart)) { // 列可空，防 NPE
                todayCorrect += nvl(e.getCorrect());
                todayTotal += nvl(e.getTotal());
                todayMaxStreak = Math.max(todayMaxStreak, nvl(e.getStreakPeak()));
            }
        }

        List<Object> best = recordDao.selectObjs(new QueryWrapper<MathPracticeRecordEntity>()
                .select("MAX(streak_peak) AS streak_peak")
                .eq("mac_address", macAddress));
        int bestStreak = best.isEmpty() || best.get(0) == null ? 0 : ((Number) best.get(0)).intValue();

        List<MathPracticeRecordEntity> recent = recordDao.selectList(
                new LambdaQueryWrapper<MathPracticeRecordEntity>()
                        .eq(MathPracticeRecordEntity::getMacAddress, macAddress)
                        .orderByDesc(MathPracticeRecordEntity::getCreatedAt)
                        .orderByDesc(MathPracticeRecordEntity::getId) // 同秒并列的确定性 tiebreaker
                        .last("LIMIT 5"));
        SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd HH:mm");
        List<Map<String, Object>> sessions = recent.stream().map(e -> {
            Map<String, Object> item = new java.util.LinkedHashMap<>();
            item.put("time", e.getCreatedAt() == null ? null : fmt.format(e.getCreatedAt()));
            item.put("correct", e.getCorrect());
            item.put("total", e.getTotal());
            item.put("streakPeak", e.getStreakPeak());
            return item;
        }).collect(Collectors.toList());

        MathPracticeProgressVO vo = new MathPracticeProgressVO();
        vo.setTodayCorrect(todayCorrect);
        vo.setTodayTotal(todayTotal);
        vo.setTodayMaxStreak(todayMaxStreak);
        vo.setCurrentStreak(recent.isEmpty() ? 0 : nvl(recent.get(0).getStreakEnd()));
        vo.setBestStreak(bestStreak);
        vo.setWeekCorrect(weekCorrect);
        vo.setWeekTotal(weekTotal);
        vo.setWeekAccuracy(weekTotal == 0 ? 0 : Math.round(weekCorrect * 100.0f / weekTotal));
        vo.setRecentSessions(sessions);
        return vo;
    }

    @Override
    public PageData<Map<String, Object>> listRecords(Map<String, Object> params) {
        String macAddress = (String) params.get("macAddress");
        if (StringUtils.isBlank(macAddress)) {
            throw new RenException("设备MAC不能为空");
        }
        requireOwnedDevice(macAddress);

        // record 与 config 不同实体，不走 BaseServiceImpl.getPage 泛型，手工分页
        long curPage = params.get(Constant.PAGE) != null ? Long.parseLong((String) params.get(Constant.PAGE)) : 1;
        long limit = params.get(Constant.LIMIT) != null ? Long.parseLong((String) params.get(Constant.LIMIT)) : 10;
        IPage<MathPracticeRecordEntity> page = new Page<>(curPage, limit);
        LambdaQueryWrapper<MathPracticeRecordEntity> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(MathPracticeRecordEntity::getMacAddress, macAddress)
                .orderByDesc(MathPracticeRecordEntity::getCreatedAt);
        recordDao.selectPage(page, wrapper);
        SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
        List<Map<String, Object>> list = page.getRecords().stream()
                .map(entity -> {
                    Map<String, Object> item = new java.util.LinkedHashMap<>();
                    item.put("macAddress", entity.getMacAddress());
                    item.put("preset", entity.getPreset());
                    item.put("total", entity.getTotal());
                    item.put("correct", entity.getCorrect());
                    item.put("durationSeconds", entity.getDurationSeconds());
                    item.put("streakPeak", entity.getStreakPeak());
                    item.put("createdAt", entity.getCreatedAt() == null ? null : fmt.format(entity.getCreatedAt()));
                    return item;
                })
                .collect(Collectors.toList());
        return new PageData<>(list, page.getTotal());
    }

    private MathPracticeConfigEntity selectByMac(String macAddress) {
        LambdaQueryWrapper<MathPracticeConfigEntity> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(MathPracticeConfigEntity::getMacAddress, macAddress);
        return configDao.selectOne(wrapper);
    }

    /** 最近一场记录的 streak_end（无记录为 0）：续接 seed 与 currentStreak 的口径 */
    private int latestStreakEnd(String macAddress) {
        MathPracticeRecordEntity latest = recordDao.selectOne(
                new LambdaQueryWrapper<MathPracticeRecordEntity>()
                        .eq(MathPracticeRecordEntity::getMacAddress, macAddress)
                        .orderByDesc(MathPracticeRecordEntity::getCreatedAt)
                        .orderByDesc(MathPracticeRecordEntity::getId) // 同秒并列的确定性 tiebreaker
                        .last("LIMIT 1"));
        return latest == null ? 0 : nvl(latest.getStreakEnd());
    }

    private static int nvl(Integer v) {
        return v == null ? 0 : v;
    }

    /** updateById 默认忽略 null 字段，typeIds 置空（=回落预设默认）会静默失效，显式 SET 全列 */
    private void updateAllFields(MathPracticeConfigEntity entity) {
        configDao.update(null, new LambdaUpdateWrapper<MathPracticeConfigEntity>()
                .eq(MathPracticeConfigEntity::getId, entity.getId())
                .set(MathPracticeConfigEntity::getPreset, entity.getPreset())
                .set(MathPracticeConfigEntity::getTypeIds, entity.getTypeIds())
                .set(MathPracticeConfigEntity::getQuestionCount, entity.getQuestionCount())
                .set(MathPracticeConfigEntity::getUpdater, entity.getUpdater())
                .set(MathPracticeConfigEntity::getUpdatedAt, entity.getUpdatedAt()));
    }

    /** 设备必须存在且属于当前用户（家长只能配置自己的设备） */
    private void requireOwnedDevice(String macAddress) {
        DeviceEntity device = deviceService.getDeviceByMacAddress(macAddress);
        if (device == null || !device.getUserId().equals(SecurityUser.getUserId())) {
            throw new RenException("设备不存在或无权操作");
        }
    }

    private void validate(MathPracticeConfigSaveDTO dto) {
        if (!VALID_PRESETS.contains(dto.getPreset())) {
            throw new RenException("非法的年级预设: " + dto.getPreset());
        }
        if (dto.getTypeIds() != null && !dto.getTypeIds().isEmpty()) {
            Set<String> unknown = new HashSet<>(dto.getTypeIds());
            unknown.removeAll(VALID_TYPE_IDS);
            if (!unknown.isEmpty()) {
                throw new RenException("非法的题型ID: " + String.join(",", unknown));
            }
            if (new HashSet<>(dto.getTypeIds()).size() != dto.getTypeIds().size()) {
                throw new RenException("题型ID不能重复");
            }
        }
    }

    private String joinTypeIds(List<String> typeIds) {
        if (typeIds == null || typeIds.isEmpty()) {
            return null;
        }
        return String.join(",", typeIds);
    }

    private List<String> splitTypeIds(String typeIds) {
        if (StringUtils.isBlank(typeIds)) {
            return null;
        }
        return Arrays.asList(typeIds.split(","));
    }

    private MathPracticeConfigVO toVO(MathPracticeConfigEntity entity) {
        MathPracticeConfigVO vo = new MathPracticeConfigVO();
        vo.setMacAddress(entity.getMacAddress());
        vo.setPreset(entity.getPreset());
        vo.setTypeIds(splitTypeIds(entity.getTypeIds()));
        vo.setQuestionCount(entity.getQuestionCount());
        vo.setUpdatedAt(entity.getUpdatedAt());
        return vo;
    }
}
