-- 设备 Todo List 每日任务模板（spec #30 / #33 T3）
-- 每天 0 点（Asia/Shanghai）重建当日清单的种子：每日项重置未完成 ∪ 存量非每日手动项留存
CREATE TABLE `todo_daily_template` (
    `id` VARCHAR(32) NOT NULL COMMENT '唯一标识',
    `mac_address` VARCHAR(17) NOT NULL COMMENT '设备MAC地址',
    `group_key` VARCHAR(16) NOT NULL COMMENT '分组：morning/study/chores/bedtime',
    `text` VARCHAR(60) NOT NULL COMMENT '任务文本（≤30字）',
    `deadline` VARCHAR(5) COMMENT '可选截止时刻 HH:MM（T4 提醒消费，本票仅建列存值不启用）',
    `sort` INT NOT NULL DEFAULT 0 COMMENT '显示序（保存顺序即重建顺序）',
    `creator` BIGINT COMMENT '创建者',
    `created_at` DATETIME COMMENT '创建时间',
    `updater` BIGINT COMMENT '更新者',
    `updated_at` DATETIME COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_todo_daily_mac_group_text` (`mac_address`, `group_key`, `text`),
    INDEX `idx_todo_daily_mac` (`mac_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日任务模板';
