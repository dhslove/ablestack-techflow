ALTER TABLE community_case
    DROP COLUMN IF EXISTS knowledge_base_solution_selected_by_user_id,
    DROP COLUMN IF EXISTS knowledge_base_solution_selected_at;
