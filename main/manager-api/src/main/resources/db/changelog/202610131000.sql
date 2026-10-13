-- 儿童陪伴模式拦截日志表（工单 #9）
-- 环形 500 条：非豁免类（danger/privacy/profanity）超窗按最旧挤出；
-- care（关怀）/redline（红线）豁免，永不挤出（裁剪逻辑见
-- AgentInterceptionLogDao.xml 的 trimEvictable）
CREATE TABLE IF NOT EXISTS `ai_agent_interception_log` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `agent_id` VARCHAR(32) NOT NULL COMMENT '智能体ID（环形窗口按智能体隔离）',
    `category` VARCHAR(16) NOT NULL COMMENT '拦截类别: care/redline/danger/privacy/profanity',
    `user_text` TEXT NULL COMMENT '孩子原话',
    `model_reply` TEXT NULL COMMENT '模型原回复',
    `actual_reply` TEXT NULL COMMENT '孩子实际听到的内容',
    `occurred_at` DATETIME NOT NULL COMMENT '拦截发生时间（Python 侧事件时间戳）',
    `created_at` DATETIME DEFAULT NULL COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT NULL COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_agent_category_id` (`agent_id`, `category`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='儿童陪伴模式拦截日志表';
