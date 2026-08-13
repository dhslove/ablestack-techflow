ALTER TABLE community_case
    ADD COLUMN IF NOT EXISTS conversation_state varchar(32) NOT NULL DEFAULT 'WAITING_REVIEW'
        CHECK (conversation_state IN ('ANALYZING','WAITING_REQUESTER','WAITING_REVIEW','WAITING_RESOLUTION','RESOLVED')),
    ADD COLUMN IF NOT EXISTS requester_user_id varchar(128),
    ADD COLUMN IF NOT EXISTS last_seen_post_id varchar(64),
    ADD COLUMN IF NOT EXISTS context_version integer NOT NULL DEFAULT 0 CHECK (context_version >= 0),
    ADD COLUMN IF NOT EXISTS resolved_post_id varchar(64),
    ADD COLUMN IF NOT EXISTS resolved_by_user_id varchar(128),
    ADD COLUMN IF NOT EXISTS resolved_at timestamptz,
    ADD COLUMN IF NOT EXISTS reopened_at timestamptz;

UPDATE community_case
SET requester_user_id = COALESCE(requester_user_id, source_metadata->>'authorId'),
    context_version = GREATEST(context_version, 1),
    conversation_state = CASE
        WHEN state = 'DRAFT_PENDING' THEN 'WAITING_REVIEW'
        WHEN state = 'PUBLISHED' THEN 'WAITING_RESOLUTION'
        ELSE conversation_state
    END;

CREATE TABLE IF NOT EXISTS community_turn (
    id uuid PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES community_case(id) ON DELETE CASCADE,
    source_post_id varchar(64) NOT NULL,
    post_number integer,
    author_user_id varchar(128) NOT NULL,
    role varchar(16) NOT NULL CHECK (role IN ('REQUESTER','STAFF','ASSISTANT')),
    content text NOT NULL,
    artifact_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    correlation_id varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, source_post_id)
);

CREATE TABLE IF NOT EXISTS community_response (
    id uuid PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES community_case(id) ON DELETE CASCADE,
    draft_version integer NOT NULL CHECK (draft_version > 0),
    state varchar(32) NOT NULL CHECK (state IN ('DRAFT_PENDING','REJECTED','PUBLISHED')),
    answer text,
    answer_state varchar(32),
    review_post_id varchar(64),
    review_post_url text,
    reviewer varchar(128),
    published_at timestamptz,
    correlation_id varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, draft_version)
);

CREATE INDEX IF NOT EXISTS community_turn_case_number_idx ON community_turn(case_id, post_number, created_at);
CREATE INDEX IF NOT EXISTS community_response_case_version_idx ON community_response(case_id, draft_version DESC);
CREATE INDEX IF NOT EXISTS community_case_conversation_state_idx ON community_case(conversation_state, updated_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON community_turn, community_response TO techflow_rag_app;
