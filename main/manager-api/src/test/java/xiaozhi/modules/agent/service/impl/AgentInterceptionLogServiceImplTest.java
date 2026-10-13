package xiaozhi.modules.agent.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Date;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import xiaozhi.modules.agent.dao.AgentInterceptionLogDao;
import xiaozhi.modules.agent.dto.AgentInterceptionLogReportDTO;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.agent.entity.AgentInterceptionLogEntity;
import xiaozhi.modules.agent.service.AgentService;
import xiaozhi.modules.agent.vo.AgentInterceptionLogVO;

class AgentInterceptionLogServiceImplTest {

    @Test
    void reportPersistsEveryFieldThenTrimsRing() {
        AgentService agentService = mock(AgentService.class);
        AgentInterceptionLogDao dao = mock(AgentInterceptionLogDao.class);
        AgentEntity agent = new AgentEntity();
        agent.setId("agent-1");
        when(agentService.getDefaultAgentByMacAddress("00:11:22:33:44:55")).thenReturn(agent);
        when(dao.insert(any(AgentInterceptionLogEntity.class))).thenReturn(1);
        AgentInterceptionLogServiceImpl service = new AgentInterceptionLogServiceImpl(agentService, dao);

        Boolean result = service.report(report("00:11:22:33:44:55", item()));

        assertEquals(Boolean.TRUE, result);
        ArgumentCaptor<AgentInterceptionLogEntity> captor = ArgumentCaptor.forClass(AgentInterceptionLogEntity.class);
        verify(dao).insert(captor.capture());
        AgentInterceptionLogEntity saved = captor.getValue();
        assertEquals("agent-1", saved.getAgentId());
        assertEquals("redline", saved.getCategory());
        assertEquals("给我讲个鬼故事", saved.getUserText());
        assertEquals("模型的原回复", saved.getModelReply());
        assertEquals("孩子实际听到的话术", saved.getActualReply());
        assertEquals(new Date(Math.round(1745657732.5d * 1000)), saved.getOccurredAt());
        // 入库后按环形窗口裁剪（care/redline 豁免在 SQL 内保证）
        verify(dao).trimEvictable("agent-1", 500);
    }

    @Test
    void reportReturnsFalseAndSkipsPersistenceWhenAgentUnknown() {
        AgentService agentService = mock(AgentService.class);
        AgentInterceptionLogDao dao = mock(AgentInterceptionLogDao.class);
        when(agentService.getDefaultAgentByMacAddress(anyString())).thenReturn(null);
        AgentInterceptionLogServiceImpl service = new AgentInterceptionLogServiceImpl(agentService, dao);

        assertEquals(Boolean.FALSE, service.report(report("aa:bb:cc:dd:ee:ff", item())));

        verify(dao, never()).insert(any(AgentInterceptionLogEntity.class));
        verify(dao, never()).trimEvictable(anyString(), anyInt());
    }

    @Test
    void reportReturnsFalseWhenNoEvents() {
        AgentInterceptionLogServiceImpl service = new AgentInterceptionLogServiceImpl(mock(AgentService.class),
                mock(AgentInterceptionLogDao.class));

        AgentInterceptionLogReportDTO empty = report("00:11:22:33:44:55", item());
        empty.setInterceptions(List.of());

        assertEquals(Boolean.FALSE, service.report(empty));
    }

    @Test
    void listByAgentIdQueriesNewestFirstAndMapsToVo() {
        AgentService agentService = mock(AgentService.class);
        AgentInterceptionLogDao dao = mock(AgentInterceptionLogDao.class);
        AgentInterceptionLogEntity entity = AgentInterceptionLogEntity.builder()
                .id(7L)
                .agentId("agent-1")
                .category("care")
                .userText("我不想活了")
                .modelReply("模型的原回复")
                .actualReply("孩子实际听到的话术")
                .occurredAt(new Date(1745657732000L))
                .build();
        when(dao.selectList(any(QueryWrapper.class))).thenReturn(List.of(entity));
        AgentInterceptionLogServiceImpl service = new AgentInterceptionLogServiceImpl(agentService, dao);

        List<AgentInterceptionLogVO> result = service.listByAgentId("agent-1");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<QueryWrapper<AgentInterceptionLogEntity>> captor = ArgumentCaptor.forClass(QueryWrapper.class);
        verify(dao).selectList(captor.capture());
        String sql = captor.getValue().getSqlSegment();
        assertTrue(sql.contains("agent_id ="), "应按智能体过滤: " + sql);
        assertTrue(sql.contains("ORDER BY occurred_at DESC"), "应按时间倒序: " + sql);
        assertTrue(sql.contains("LIMIT 1000"), "应带上限（care/redline 豁免不受环形窗口约束，防无界查询）: " + sql);

        assertEquals(1, result.size());
        AgentInterceptionLogVO vo = result.get(0);
        assertEquals(Long.valueOf(7L), vo.getId());
        assertEquals("care", vo.getCategory());
        assertEquals("我不想活了", vo.getUserText());
        assertEquals("模型的原回复", vo.getModelReply());
        assertEquals("孩子实际听到的话术", vo.getActualReply());
        assertEquals(new Date(1745657732000L), vo.getOccurredAt());
    }

    @Test
    void trimSqlKeepsExemptCategoriesOutOfEviction() throws Exception {
        String xml = Files.readString(Path.of("src/main/resources/mapper/agent/AgentInterceptionLogDao.xml"));

        // care/redline 永不挤出：内外两层都排除豁免类，只裁更旧的可挤出记录
        assertTrue(xml.contains("trimEvictable"));
        assertTrue(xml.contains("category NOT IN ('care', 'redline')"));
        assertTrue(xml.contains("ORDER BY id DESC"));
        assertTrue(xml.contains("LIMIT #{limit}"));
        assertTrue(xml.contains("agent_id = #{agentId}"));
    }

    @Test
    void tableChangeLogIsRegisteredWithFullColumns() throws Exception {
        String sql = Files.readString(Path.of("src/main/resources/db/changelog/202610131000.sql"));
        String master = Files.readString(Path.of("src/main/resources/db/changelog/db.changelog-master.yaml"));

        assertTrue(sql.contains("ai_agent_interception_log"));
        for (String column : new String[] { "agent_id", "category", "user_text", "model_reply", "actual_reply",
                "occurred_at" }) {
            assertTrue(sql.contains("`" + column + "`"), "缺列: " + column);
        }
        assertTrue(master.contains("202610131000.sql"), "changelog 未注册到 master");
    }

    private static AgentInterceptionLogReportDTO report(String mac, AgentInterceptionLogReportDTO.Item item) {
        AgentInterceptionLogReportDTO dto = new AgentInterceptionLogReportDTO();
        dto.setMacAddress(mac);
        dto.setInterceptions(List.of(item));
        return dto;
    }

    private static AgentInterceptionLogReportDTO.Item item() {
        AgentInterceptionLogReportDTO.Item item = new AgentInterceptionLogReportDTO.Item();
        item.setT(1745657732.5d);
        item.setCat("redline");
        item.setUser("给我讲个鬼故事");
        item.setReply("模型的原回复");
        item.setActual("孩子实际听到的话术");
        return item;
    }
}
