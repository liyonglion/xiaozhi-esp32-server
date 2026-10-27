-- 设备 Todo List（spec #30 / #31 T1）：清单镜像 + 完成事件
-- 设备 NVS(todos_json) 是清单唯一真值源，todo_mirror 为服务端镜像（mac 唯一、整表 last-writer-wins）
CREATE TABLE `todo_mirror` (
    `id` VARCHAR(32) NOT NULL COMMENT '唯一标识',
    `mac_address` VARCHAR(17) NOT NULL COMMENT '设备MAC地址',
    `items` TEXT COMMENT '清单镜像 JSON 数组 [{"text":..,"done":..}]',
    `sync_enabled` TINYINT NOT NULL DEFAULT 1 COMMENT '同步开关（设备级，默认开）',
    `quiet_start` VARCHAR(5) DEFAULT '21:00' COMMENT '提醒静默起始 HH:MM',
    `quiet_end` VARCHAR(5) DEFAULT '07:00' COMMENT '提醒静默结束 HH:MM',
    `max_items` TINYINT DEFAULT 30 COMMENT '清单条数软上限（NVS 单键 ~4KB 物理边界之内）',
    `pending` TINYINT NOT NULL DEFAULT 0 COMMENT '待下发标记（家长编辑后等待送达设备，T2）',
    `source` VARCHAR(16) DEFAULT 'voice' COMMENT '最近一次镜像写入来源：voice/admin/daily',
    `creator` BIGINT COMMENT '创建者',
    `created_at` DATETIME COMMENT '创建时间',
    `updater` BIGINT COMMENT '更新者',
    `updated_at` DATETIME COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_todo_mirror_mac` (`mac_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='设备任务清单镜像';

-- 完成事件：上报与旧镜像 diff 出「由未完成变为完成」逐次记录（激励统计/争议仲裁数据地基）
CREATE TABLE `todo_event` (
    `id` VARCHAR(32) NOT NULL COMMENT '唯一标识',
    `mac_address` VARCHAR(17) NOT NULL COMMENT '设备MAC地址',
    `text` VARCHAR(60) NOT NULL COMMENT '完成时的任务文本（≤30字）',
    `created_at` DATETIME COMMENT '完成时间',
    PRIMARY KEY (`id`),
    INDEX `idx_todo_event_mac` (`mac_address`),
    INDEX `idx_todo_event_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='设备任务完成事件';
