CREATE TABLE IF NOT EXISTS chat_assist_job (
    id uuid PRIMARY KEY,
    user_id varchar(128) NOT NULL REFERENCES chat_assist_conversation(user_id) ON DELETE CASCADE,
    context_version integer NOT NULL CHECK (context_version > 0),
    post_id varchar(128) NOT NULL,
    state varchar(16) NOT NULL CHECK (state IN (
        'PENDING','RUNNING','RETRYING','COMPLETED','DEAD_LETTER','CANCELLED'
    )),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    last_error_type varchar(128),
    correlation_id varchar(128) NOT NULL,
    next_attempt_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, context_version, post_id)
);

CREATE INDEX IF NOT EXISTS chat_assist_job_ready_idx
    ON chat_assist_job(state, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS chat_assist_job_user_context_idx
    ON chat_assist_job(user_id, context_version, created_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON chat_assist_job TO techflow_rag_app;
