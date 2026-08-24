-- 0006: per-user token version for JWT revocation (force logout on password change)
ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0;
