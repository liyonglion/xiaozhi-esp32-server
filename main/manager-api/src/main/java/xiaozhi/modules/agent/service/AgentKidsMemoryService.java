package xiaozhi.modules.agent.service;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * 儿童长期记忆代理服务（工单 #10）
 *
 * <p>
 * 家长页不直连小智服务：本服务把请求转发到 Python 8003 的
 * /xiaozhi/kids/memory/* 端点（core/api/kids_memory_handler.py），
 * 携带 Bearer server.secret。记忆按活跃实例/最近角色定位（单家庭单孩子
 * 设备假设，见 mem_kids 注释）。
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
public interface AgentKidsMemoryService {

    /**
     * 长期记忆条目列表（[{id, ts, text}]，ts 升序）
     */
    JsonNode list();

    /**
     * 逐条删除；返回是否确实删了一条
     */
    Boolean delete(Long entryId);

    /**
     * 全量清除（条目与滚动摘要一起清）；返回是否成功
     */
    Boolean clear();
}
