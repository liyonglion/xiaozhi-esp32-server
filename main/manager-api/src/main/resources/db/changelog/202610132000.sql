-- 智能体表添加孩子档案字段（儿童陪伴模式：enabled 开关 + 称呼/出生年月/性格/爱好/嘱托/禁忌 的 JSON）
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_agent' AND COLUMN_NAME = 'kid_profile');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE `ai_agent` ADD COLUMN `kid_profile` LONGTEXT NULL COMMENT ''孩子档案JSON'' AFTER `summary_memory`', 'SELECT ''Column kid_profile already exists'' AS msg');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
