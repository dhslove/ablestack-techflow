ALTER TABLE chat_assist_turn
    ADD COLUMN IF NOT EXISTS artifact_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS artifact_warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS artifact_checked boolean NOT NULL DEFAULT false;

UPDATE chat_assist_turn SET artifact_checked=true WHERE role='ASSISTANT';

ALTER TABLE chat_assist_turn
    DROP CONSTRAINT IF EXISTS chat_assist_turn_artifact_ids_array,
    DROP CONSTRAINT IF EXISTS chat_assist_turn_artifact_warnings_array;
ALTER TABLE chat_assist_turn
    ADD CONSTRAINT chat_assist_turn_artifact_ids_array CHECK (jsonb_typeof(artifact_ids)='array'),
    ADD CONSTRAINT chat_assist_turn_artifact_warnings_array CHECK (jsonb_typeof(artifact_warnings)='array');
