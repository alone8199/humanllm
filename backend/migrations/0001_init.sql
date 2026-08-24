-- HumanLLM initial schema (portable SQLite / PostgreSQL).
-- Applied idempotently by app.migrate.run_migrations().

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(255) UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'consumer',
    balance_cents INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_prefix VARCHAR(32) NOT NULL,
    key_hash VARCHAR(64) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL DEFAULT 'default',
    is_active BOOLEAN NOT NULL DEFAULT 1,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP,
    UNIQUE (key_hash)
);

CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(128) NOT NULL DEFAULT '',
    hashed_password VARCHAR(255) NOT NULL,
    owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'offline',
    current_task_id VARCHAR(36),
    skills JSON,
    earnings_cents INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(128) NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    price_per_request_cents INTEGER NOT NULL DEFAULT 0,
    price_per_1k_chars_cents INTEGER NOT NULL DEFAULT 0,
    price_per_minute_cents INTEGER NOT NULL DEFAULT 0,
    concurrency INTEGER NOT NULL DEFAULT 1,
    timeout_seconds INTEGER NOT NULL DEFAULT 600,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS worker_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    model_name VARCHAR(64) NOT NULL REFERENCES models(name) ON DELETE CASCADE,
    UNIQUE (worker_id, model_name)
);

CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR(36) PRIMARY KEY,
    model VARCHAR(64) NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    messages JSON NOT NULL DEFAULT '[]',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    assigned_worker_id INTEGER REFERENCES workers(id) ON DELETE SET NULL,
    stream BOOLEAN NOT NULL DEFAULT 0,
    precharge_cents INTEGER NOT NULL DEFAULT 0,
    reply_text TEXT NOT NULL DEFAULT '',
    usage JSON,
    error TEXT,
    finish_reason VARCHAR(32),
    created_at TIMESTAMP,
    assigned_at TIMESTAMP,
    completed_at TIMESTAMP,
    timeout_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_tasks_model ON tasks(model);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS ix_tasks_created ON tasks(created_at);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id VARCHAR(36) NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    kind VARCHAR(16) NOT NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'url',
    filename VARCHAR(255) NOT NULL DEFAULT '',
    content_type VARCHAR(128),
    storage_key VARCHAR(512),
    url TEXT,
    size INTEGER,
    created_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_attachments_task ON attachments(task_id);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id VARCHAR(36) REFERENCES tasks(id) ON DELETE SET NULL,
    kind VARCHAR(32) NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    worker_id INTEGER REFERENCES workers(id) ON DELETE SET NULL,
    amount_cents INTEGER NOT NULL,
    note VARCHAR(255),
    created_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_transactions_kind ON transactions(kind);
CREATE INDEX IF NOT EXISTS ix_transactions_task ON transactions(task_id);

CREATE TABLE IF NOT EXISTS uploaded_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    storage_key VARCHAR(512) NOT NULL,
    filename VARCHAR(255) NOT NULL DEFAULT '',
    content_type VARCHAR(128),
    size INTEGER,
    owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id VARCHAR(36),
    actor VARCHAR(32),
    kind VARCHAR(32) NOT NULL,
    detail JSON,
    created_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_event_logs_created ON event_logs(created_at);
