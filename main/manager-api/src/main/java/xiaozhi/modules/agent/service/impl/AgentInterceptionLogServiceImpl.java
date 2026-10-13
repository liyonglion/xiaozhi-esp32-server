package xiaozhi.modules.agent.service.impl;

import java.util.Date;
import java.util.List;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.utils.ConvertUtils;
import xiaozhi.modules.agent.dao.AgentInterceptionLogDao;
import xiaozhi.modules.agent.dto.AgentInterceptionLogReportDTO;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.agent.entity.AgentInterceptionLogEntity;
import xiaozhi.modules.agent.service.AgentInterceptionLogService;
import xiaozhi.modules.agent.service.AgentService;
import xiaozhi.modules.agent.vo.AgentInterceptionLogVO;

/**
 * {@link AgentInterceptionLogService} impl
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class AgentInterceptionLogServiceImpl implements AgentInterceptionLogService {
    /**
     * 环形窗口：非豁免类（danger/privacy/profanity）保留条数上限；
     * care/redline 豁免挤出，不受此限
     */
    static final int RING_LIMIT = 500;

    private final AgentService agentService;
    private final AgentInterceptionLogDao agentInterceptionLogDao;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public Boolean report(AgentInterceptionLogReportDTO report) {
        List<AgentInterceptionLogReportDTO.Item> events = report.getInterceptions();
        if (events == null || events.isEmpty()) {
            return Boolean.FALSE;
        }
        AgentEntity agent = agentService.getDefaultAgentByMacAddress(report.getMacAddress());
        if (agent == null) {
            log.warn("拦截日志上报时，未找到mac地址为 {} 的设备对应智能体", report.getMacAddress());
            return Boolean.FALSE;
        }
        Date now = new Date();
        for (AgentInterceptionLogReportDTO.Item item : events) {
            long millis = null != item.getT() ? Math.round(item.getT() * 1000) : now.getTime();
            agentInterceptionLogDao.insert(AgentInterceptionLogEntity.builder()
                    .agentId(agent.getId())
                    .category(item.getCat())
                    .userText(item.getUser())
                    .modelReply(item.getReply())
                    .actualReply(item.getActual())
                    .occurredAt(new Date(millis))
                    .createdAt(now)
                    .build());
        }
        agentInterceptionLogDao.trimEvictable(agent.getId(), RING_LIMIT);
        log.info("设备 {} 对应智能体 {} 拦截日志上报 {} 条", report.getMacAddress(), agent.getId(), events.size());
        return Boolean.TRUE;
    }

    @Override
    public List<AgentInterceptionLogVO> listByAgentId(String agentId) {
        QueryWrapper<AgentInterceptionLogEntity> wrapper = new QueryWrapper<>();
        // 时间倒序（id 作同秒内稳定次序键）；环形窗口限定结果规模
        wrapper.eq("agent_id", agentId)
                .orderByDesc("occurred_at")
                .orderByDesc("id");
        List<AgentInterceptionLogEntity> entities = agentInterceptionLogDao.selectList(wrapper);
        return ConvertUtils.sourceToTarget(entities, AgentInterceptionLogVO.class);
    }
}
