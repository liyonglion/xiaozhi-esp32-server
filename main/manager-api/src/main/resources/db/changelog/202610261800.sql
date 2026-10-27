-- 口算练习设备配置（地图 #24 决议：设备级一份，题型 ID 集合 + 参数）
CREATE TABLE `math_practice_config` (
    `id` VARCHAR(32) NOT NULL COMMENT '唯一标识',
    `mac_address` VARCHAR(17) NOT NULL COMMENT '设备MAC地址',
    `preset` VARCHAR(16) NOT NULL DEFAULT 'g1a' COMMENT '年级预设：preschool/g1a/g1b/g2a/g2b',
    `type_ids` VARCHAR(512) DEFAULT NULL COMMENT '微调后的题型ID集合（逗号分隔），空=使用预设默认',
    `question_count` TINYINT DEFAULT 10 COMMENT '每轮题量（5-20）',
    `creator` BIGINT COMMENT '创建者',
    `created_at` DATETIME COMMENT '创建时间',
    `updater` BIGINT COMMENT '更新者',
    `updated_at` DATETIME COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_math_practice_config_mac` (`mac_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='口算练习设备配置';

-- 口算练习记录（#24 决议：最小版，一次会话一行，只读）
CREATE TABLE `math_practice_record` (
    `id` VARCHAR(32) NOT NULL COMMENT '唯一标识',
    `mac_address` VARCHAR(17) NOT NULL COMMENT '设备MAC地址',
    `preset` VARCHAR(16) COMMENT '当时使用的年级预设',
    `total` TINYINT COMMENT '本轮题量',
    `correct` TINYINT COMMENT '答对题数',
    `duration_seconds` INT COMMENT '本轮用时（秒）',
    `created_at` DATETIME COMMENT '练习时间',
    PRIMARY KEY (`id`),
    INDEX `idx_math_practice_record_mac` (`mac_address`),
    INDEX `idx_math_practice_record_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='口算练习记录';
