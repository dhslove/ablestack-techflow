ALTER TABLE community_case
    ADD COLUMN IF NOT EXISTS knowledge_base_post_id varchar(64),
    ADD COLUMN IF NOT EXISTS knowledge_base_post_url text,
    ADD COLUMN IF NOT EXISTS knowledge_base_source_post_id varchar(64),
    ADD COLUMN IF NOT EXISTS knowledge_base_answer text,
    ADD COLUMN IF NOT EXISTS knowledge_base_version integer NOT NULL DEFAULT 0 CHECK (knowledge_base_version >= 0),
    ADD COLUMN IF NOT EXISTS knowledge_base_published_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS community_case_knowledge_base_post_idx
    ON community_case(knowledge_base_post_id)
    WHERE knowledge_base_post_id IS NOT NULL;
