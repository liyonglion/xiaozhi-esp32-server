-- 口算 streak（#29 决议：单计数器跨会话续接；派生口径 bestStreak=全史 MAX(streak_peak)、
-- todayMaxStreak=今日各会话 MAX(streak_peak)、currentStreak=最近一条 streak_end）
ALTER TABLE `math_practice_record`
    ADD COLUMN `streak_end` INT NOT NULL DEFAULT 0 COMMENT '会话收尾时连对值（续接+currentStreak）' AFTER `duration_seconds`,
    ADD COLUMN `streak_peak` INT NOT NULL DEFAULT 0 COMMENT '本会话连对峰值' AFTER `streak_end`;
