DROP INDEX IF EXISTS community_case_knowledge_base_post_idx;

ALTER TABLE community_case
    DROP COLUMN IF EXISTS knowledge_base_published_at,
    DROP COLUMN IF EXISTS knowledge_base_version,
    DROP COLUMN IF EXISTS knowledge_base_answer,
    DROP COLUMN IF EXISTS knowledge_base_source_post_id,
    DROP COLUMN IF EXISTS knowledge_base_post_url,
    DROP COLUMN IF EXISTS knowledge_base_post_id;
