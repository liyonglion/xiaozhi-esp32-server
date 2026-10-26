package xiaozhi.modules.mathpractice.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.util.Date;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import jakarta.servlet.http.HttpServletResponse;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.mathpractice.controller.MathPracticeController;
import xiaozhi.modules.mathpractice.dao.MathPracticeConfigDao;
import xiaozhi.modules.mathpractice.dao.MathPracticeRecordDao;
import xiaozhi.modules.mathpractice.dto.MathPracticeReportDTO;
import xiaozhi.modules.mathpractice.entity.MathPracticeRecordEntity;
import xiaozhi.modules.mathpractice.service.MathPracticeService;
import xiaozhi.modules.mathpractice.vo.MathPracticeConfigVO;
import xiaozhi.modules.mathpractice.vo.MathPracticeProgressVO;

class MathPracticeServiceImplTest {

    @Test
    void getProgressAggregatesTodayWeekBestAndRecentSessions() {
        MathPracticeRecordDao recordDao = mock(MathPracticeRecordDao.class);
        // 调用顺序：近 7 天行（今日 2 场 + 26h 前 1 场）→ 全史 MAX(streak_peak) → 最近 5 场
        Date now = new Date();
        MathPracticeRecordEntity today1 = record("AA", 10, 8, 3, 4, now);
        MathPracticeRecordEntity today2 = record("AA", 10, 5, 0, 1, new Date(now.getTime()));  // 与 today1 同刻，防跨零点误判
        MathPracticeRecordEntity yesterday = record("AA", 10, 9, 2, 9, new Date(now.getTime() - 26 * 3600_000));
        MathPracticeRecordEntity old = record("AA", 10, 10, 10, 12, new Date(now.getTime() - 30L * 24 * 3600_000));
        when(recordDao.selectList(any())).thenReturn(List.of(today1, today2, yesterday), List.of(old, today1));
        when(recordDao.selectObjs(any())).thenReturn(List.of(12));

        MathPracticeProgressVO vo = newService(recordDao).getProgress("AA");

        assertEquals(13, vo.getTodayCorrect());   // 8 + 5
        assertEquals(20, vo.getTodayTotal());     // 10 + 10
        assertEquals(4, vo.getTodayMaxStreak());  // max(today1 peak 4, today2 peak 1)
        assertEquals(10, vo.getCurrentStreak());  // 最近一场（old）的 streak_end
        assertEquals(12, vo.getBestStreak());     // 全史 MAX(streak_peak)
        assertEquals(22, vo.getWeekCorrect());    // 8 + 5 + 9
        assertEquals(30, vo.getWeekTotal());
        assertEquals(73, vo.getWeekAccuracy());   // 22/30 = 73.3%
        assertEquals(2, vo.getRecentSessions().size());
        assertEquals(10, vo.getRecentSessions().get(0).get("correct")); // 最近在前
        assertEquals(4, vo.getRecentSessions().get(1).get("streakPeak")); // today1 的 peak
    }

    @Test
    void getProgressWithNoRecordsReturnsZeros() {
        MathPracticeRecordDao recordDao = mock(MathPracticeRecordDao.class);
        when(recordDao.selectList(any())).thenReturn(List.of());
        when(recordDao.selectObjs(any())).thenReturn(List.of());

        MathPracticeProgressVO vo = newService(recordDao).getProgress("AA");

        assertEquals(0, vo.getTodayCorrect());
        assertEquals(0, vo.getWeekTotal());
        assertEquals(0, vo.getWeekAccuracy());
        assertEquals(0, vo.getCurrentStreak());
        assertEquals(0, vo.getBestStreak());
        assertEquals(0, vo.getRecentSessions().size());
    }

    @Test
    void getConfigByMacReturnsStreakEndEvenWhenUnconfigured() {
        MathPracticeRecordDao recordDao = mock(MathPracticeRecordDao.class);
        MathPracticeConfigDao configDao = mock(MathPracticeConfigDao.class);
        when(configDao.selectOne(any())).thenReturn(null);
        // 调用顺序：selectOne 取最近记录（config 未配置路径）→ streak_end=6
        when(recordDao.selectOne(any())).thenReturn(record("AA", 10, 8, 6, 6, new Date()));

        MathPracticeConfigVO vo = new MathPracticeServiceImpl(configDao, recordDao, mock(DeviceService.class))
                .getConfigByMac("AA");

        assertEquals(6, vo.getStreakEnd()); // 未配置也返回体：续接值随本接口捎回（#29 零新请求）
        assertEquals("AA", vo.getMacAddress());
    }

    @Test
    void reportRecordPersistsStreakValues() {
        MathPracticeRecordDao recordDao = mock(MathPracticeRecordDao.class);
        MathPracticeReportDTO dto = new MathPracticeReportDTO();
        dto.setMacAddress("AA");
        dto.setTotal(10);
        dto.setCorrect(7);
        dto.setStreakEnd(4);
        dto.setStreakPeak(5);

        newService(recordDao).reportRecord(dto);

        ArgumentCaptor<MathPracticeRecordEntity> captor = ArgumentCaptor.forClass(MathPracticeRecordEntity.class);
        verify(recordDao).insert(captor.capture());
        assertEquals(4, captor.getValue().getStreakEnd());
        assertEquals(5, captor.getValue().getStreakPeak());
    }

    @Test
    void progressEndpointRejectsWrongOrMissingTokenAndPassesCorrectOne() throws Exception {
        MathPracticeService service = mock(MathPracticeService.class);
        MathPracticeController controller = new MathPracticeController(service, "tk");
        HttpServletResponse resp = mock(HttpServletResponse.class);

        controller.getProgress("AA", "wrong", resp);
        controller.getProgress("AA", null, resp);
        controller.getProgress("AA", "", resp);
        new MathPracticeController(service, "").getProgress("AA", "tk", resp); // 未配 token：拒绝所有
        verify(resp, times(4)).sendError(HttpServletResponse.SC_UNAUTHORIZED);
        verifyNoInteractions(service);

        when(service.getProgress("AA")).thenReturn(new MathPracticeProgressVO());
        assertNotNull(controller.getProgress("AA", "tk", resp).getData());
    }

    private static MathPracticeServiceImpl newService(MathPracticeRecordDao recordDao) {
        return new MathPracticeServiceImpl(mock(MathPracticeConfigDao.class), recordDao, mock(DeviceService.class));
    }

    private static MathPracticeRecordEntity record(String mac, int total, int correct, int streakEnd, int streakPeak, Date createdAt) {
        MathPracticeRecordEntity e = new MathPracticeRecordEntity();
        e.setMacAddress(mac);
        e.setTotal(total);
        e.setCorrect(correct);
        e.setStreakEnd(streakEnd);
        e.setStreakPeak(streakPeak);
        e.setCreatedAt(createdAt);
        return e;
    }
}
