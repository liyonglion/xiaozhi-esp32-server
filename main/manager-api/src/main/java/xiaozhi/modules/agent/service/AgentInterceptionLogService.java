package xiaozhi.modules.agent.service;

import java.util.List;

import xiaozhi.modules.agent.dto.AgentInterceptionLogReportDTO;
import xiaozhi.modules.agent.vo.AgentInterceptionLogVO;

/**
 * 儿童陪伴模式拦截日志service
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
public interface AgentInterceptionLogService {

    /**
     * 接收小智服务上报的拦截事件并入库（入库后按环形窗口裁剪）
     *
     * @param report 上报请求（MAC地址 + 拦截事件列表）
     * @return 上报结果，true表示成功，false表示失败
     */
    Boolean report(AgentInterceptionLogReportDTO report);

    /**
     * 查询智能体的拦截日志（按时间倒序，供家长页展示）
     *
     * @param agentId 智能体ID
     * @return 拦截日志列表
     */
    List<AgentInterceptionLogVO> listByAgentId(String agentId);
}
