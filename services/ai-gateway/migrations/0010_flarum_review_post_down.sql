DROP INDEX IF EXISTS community_case_review_post_idx;

ALTER TABLE community_case
    DROP COLUMN IF EXISTS review_post_url,
    DROP COLUMN IF EXISTS review_post_id;
