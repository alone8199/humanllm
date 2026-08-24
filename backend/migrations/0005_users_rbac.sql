-- 0005_users_rbac.sql
-- Multi-user RBAC: add the permissions column and promote the existing single
-- admin account to super_admin. The role column is VARCHAR(16) without a CHECK
-- constraint, so the UPDATE is safe on any existing database.

ALTER TABLE users ADD COLUMN permissions JSON;

UPDATE users SET role = 'super_admin' WHERE role = 'admin';
