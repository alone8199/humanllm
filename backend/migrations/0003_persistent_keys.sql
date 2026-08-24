-- 0003_persistent_keys.sql
-- Makes API keys permanently viewable: store the full key on the row so the
-- admin can always see it in the UI (previously only the SHA-256 hash and a
-- prefix were kept, so the full key could only be shown once at creation).

ALTER TABLE api_keys ADD COLUMN full_key VARCHAR(128);
