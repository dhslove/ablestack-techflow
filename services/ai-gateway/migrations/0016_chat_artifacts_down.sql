ALTER TABLE chat_assist_turn
    DROP CONSTRAINT IF EXISTS chat_assist_turn_artifact_ids_array,
    DROP CONSTRAINT IF EXISTS chat_assist_turn_artifact_warnings_array,
    DROP COLUMN IF EXISTS artifact_checked,
    DROP COLUMN IF EXISTS artifact_warnings,
    DROP COLUMN IF EXISTS artifact_ids;
