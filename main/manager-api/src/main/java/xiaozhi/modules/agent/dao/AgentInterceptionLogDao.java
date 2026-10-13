package xiaozhi.modules.agent.dao;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.agent.entity.AgentInterceptionLogEntity;

/**
 * {@link AgentInterceptionLogEntity} 儿童陪伴模式拦截日志Dao对象
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
@Mapper
public interface AgentInterceptionLogDao extends BaseMapper<AgentInterceptionLogEntity> {

    /**
     * 环形裁剪：保留该智能体最新的 limit 条可挤出记录，删除更旧的可挤出记录；
     * care/redline（关怀/红线）豁免类永不删除。
     *
     * @param agentId 智能体ID
     * @param limit   环形窗口大小（非豁免类保留条数）
     */
    void trimEvictable(@Param("agentId") String agentId, @Param("limit") int limit);
}
