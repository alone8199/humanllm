-- 0007: 标记初始管理员不可删除
ALTER TABLE users ADD COLUMN is_initial_admin BOOLEAN NOT NULL DEFAULT 0;
