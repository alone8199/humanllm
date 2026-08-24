-- 0004_session_id.sql
-- Multi-round tool calling: tasks that returned tool_calls can be continued
-- by a follow-up request carrying tool results. session_id links those rounds
-- to the same task row so the human worker sees one continuous conversation.

ALTER TABLE tasks ADD COLUMN session_id VARCHAR(64);
