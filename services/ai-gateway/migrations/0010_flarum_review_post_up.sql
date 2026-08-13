ALTER TABLE community_case
    ADD COLUMN IF NOT EXISTS review_post_id varchar(32),
    ADD COLUMN IF NOT EXISTS review_post_url text;

CREATE UNIQUE INDEX IF NOT EXISTS community_case_review_post_idx
    ON community_case(review_post_id)
    WHERE review_post_id IS NOT NULL;
