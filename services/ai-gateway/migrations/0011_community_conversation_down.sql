DROP INDEX IF EXISTS community_case_conversation_state_idx;
DROP INDEX IF EXISTS community_response_case_version_idx;
DROP INDEX IF EXISTS community_turn_case_number_idx;
DROP TABLE IF EXISTS community_response;
DROP TABLE IF EXISTS community_turn;

ALTER TABLE community_case
    DROP COLUMN IF EXISTS reopened_at,
    DROP COLUMN IF EXISTS resolved_at,
    DROP COLUMN IF EXISTS resolved_by_user_id,
    DROP COLUMN IF EXISTS resolved_post_id,
    DROP COLUMN IF EXISTS context_version,
    DROP COLUMN IF EXISTS last_seen_post_id,
    DROP COLUMN IF EXISTS requester_user_id,
    DROP COLUMN IF EXISTS conversation_state;
