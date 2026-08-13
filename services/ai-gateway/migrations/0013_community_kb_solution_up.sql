ALTER TABLE community_case
    ADD COLUMN IF NOT EXISTS knowledge_base_solution_selected_at timestamptz,
    ADD COLUMN IF NOT EXISTS knowledge_base_solution_selected_by_user_id varchar(64);
