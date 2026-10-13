package xiaozhi.modules.agent.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 儿童陪伴模式拦截日志表
 *
 * <p>
 * 环形 500 条：非豁免类（danger/privacy/profanity）超窗按最旧挤出；
 * care（关怀）/redline（红线）豁免，永不挤出。
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
@TableName(value = "ai_agent_interception_log")
public class AgentInterceptionLogEntity {
    /**
     * 主键ID
     */
    @TableId(type = IdType.AUTO)
    private Long id;

    /**
     * 智能体ID（环形窗口按智能体隔离）
     */
    @TableField(value = "agent_id")
    private String agentId;

    /**
     * 拦截类别: care/redline/danger/privacy/profanity
     */
    @TableField(value = "category")
    private String category;

    /**
     * 孩子原话
     */
    @TableField(value = "user_text")
    private String userText;

    /**
     * 模型原回复
     */
    @TableField(value = "model_reply")
    private String modelReply;

    /**
     * 孩子实际听到的内容
     */
    @TableField(value = "actual_reply")
    private String actualReply;

    /**
     * 拦截发生时间（Python 侧事件时间戳）
     */
    @TableField(value = "occurred_at")
    private Date occurredAt;

    /**
     * 创建时间
     */
    @TableField(value = "created_at")
    private Date createdAt;

    /**
     * 更新时间
     */
    @TableField(value = "updated_at")
    private Date updatedAt;
}
