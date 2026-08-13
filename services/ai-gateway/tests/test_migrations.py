from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
UP_0001 = (ROOT / "migrations" / "0001_schema_up.sql").read_text(encoding="utf-8")
UP_0002 = (ROOT / "migrations" / "0002_source_registry_up.sql").read_text(encoding="utf-8")
UP_0003 = (ROOT / "migrations" / "0003_source_mirror_up.sql").read_text(encoding="utf-8")
UP_0004 = (ROOT / "migrations" / "0004_source_mirror_policy_up.sql").read_text(encoding="utf-8")
UP_0005 = (ROOT / "migrations" / "0005_parser_embedding_retrieval_up.sql").read_text(encoding="utf-8")
UP_0006 = (ROOT / "migrations" / "0006_orchestration_correlation_up.sql").read_text(encoding="utf-8")
UP_0007 = (ROOT / "migrations" / "0007_reindex_fk_performance_up.sql").read_text(encoding="utf-8")
UP_0011 = (ROOT / "migrations" / "0011_community_conversation_up.sql").read_text(encoding="utf-8")
UP_0012 = (ROOT / "migrations" / "0012_community_auto_publish_kb_up.sql").read_text(encoding="utf-8")
DOWN_0001 = (ROOT / "migrations" / "0001_schema_down.sql").read_text(encoding="utf-8")
DOWN_0002 = (ROOT / "migrations" / "0002_source_registry_down.sql").read_text(encoding="utf-8")
DOWN_0003 = (ROOT / "migrations" / "0003_source_mirror_down.sql").read_text(encoding="utf-8")
DOWN_0004 = (ROOT / "migrations" / "0004_source_mirror_policy_down.sql").read_text(encoding="utf-8")
UP = UP_0001 + "\n" + UP_0002 + "\n" + UP_0003 + "\n" + UP_0004 + "\n" + UP_0005 + "\n" + UP_0006 + "\n" + UP_0007
DOWN = DOWN_0004 + "\n" + DOWN_0003 + "\n" + DOWN_0002 + "\n" + DOWN_0001
BOOTSTRAP = (ROOT / "migrations" / "0000_extensions_roles_up.sql").read_text(encoding="utf-8")


class MigrationContractTest(unittest.TestCase):
    def test_exactly_nineteen_tables(self) -> None:
        tables = re.findall(r"(?im)^CREATE TABLE\s+(rag_[a-z_]+)", UP)
        self.assertEqual(19, len(tables))
        self.assertEqual(19, len(set(tables)))

    def test_down_drops_all_nineteen_tables(self) -> None:
        created = set(re.findall(r"(?im)^CREATE TABLE\s+(rag_[a-z_]+)", UP))
        dropped = set(re.findall(r"(?im)^DROP TABLE IF EXISTS\s+(rag_[a-z_]+)", DOWN))
        self.assertEqual(created, dropped)

    def test_required_extensions(self) -> None:
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", BOOTSTRAP)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pg_trgm", BOOTSTRAP)

    def test_three_group_roles_are_no_login(self) -> None:
        for role in ("techflow_rag_migrator", "techflow_rag_app", "techflow_rag_source_fetcher"):
            self.assertRegex(BOOTSTRAP, rf"CREATE ROLE {role} NOLOGIN")

    def test_provider_call_has_safe_metadata(self) -> None:
        block = UP_0001.split("CREATE TABLE rag_provider_call", 1)[1].split(");", 1)[0].lower()
        for field in ("requested_model_id", "returned_model_id", "provider_request_id", "latency_ms", "error_code"):
            self.assertIn(field, block)
        for forbidden in ("prompt ", "response ", "authorization", "api_key", "credential", "content "):
            self.assertNotIn(forbidden, block)

    def test_embedding_dimension_is_3072(self) -> None:
        self.assertIn("embedding vector(3072) NOT NULL", UP)
        self.assertIn("'OPENAI_EMBEDDING_V1'", UP)

    def test_d0_checks_exist_on_source_chunk_and_case(self) -> None:
        self.assertGreaterEqual(UP.count("CHECK (classification = 'D0')"), 3)

    def test_idempotency_is_persisted_on_mutations(self) -> None:
        self.assertGreaterEqual(UP.count("idempotency_key varchar(128)"), 5)

    def test_issue42_state_machine_and_registry_are_persisted(self) -> None:
        for state in ("REGISTERED", "QUARANTINED", "APPROVED", "INDEXING", "ACTIVE"):
            self.assertIn(f"'{state}'", UP_0002)
        self.assertEqual(9, UP_0002.count("'ACTIVE_PLUS_7D_DELETION_SLA'"))
        self.assertIn("scan_idempotency_key varchar(128) UNIQUE", UP_0002)
        self.assertIn("completion_idempotency_key varchar(128) UNIQUE", UP_0002)

    def test_quarantined_content_has_no_storage_column(self) -> None:
        file_table = UP_0002.split("CREATE TABLE rag_source_file", 1)[1].split(");", 1)[0].lower()
        finding_table = UP_0002.split("CREATE TABLE rag_source_scan_finding", 1)[1].split(");", 1)[0].lower()
        self.assertNotIn("content text", file_table)
        self.assertNotIn("content text", finding_table)

    def test_activepieces_role_is_absent(self) -> None:
        self.assertNotIn("create role activepieces", (UP + BOOTSTRAP).lower())
        self.assertNotIn("to activepieces", UP_0006.lower())

    def test_source_mirror_registry_has_seven_repositories_and_stale_policy(self) -> None:
        self.assertEqual(7, UP_0003.count("'ablecloud-team/"))
        self.assertIn("SCHEDULE_6H_RECONCILIATION", UP_0003)
        self.assertIn("DEFAULT 86400", UP_0003)

    def test_public_table_privileges_are_revoked(self) -> None:
        self.assertIn("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC", UP)

    def test_issue43_execution_and_provider_subject_are_persisted(self) -> None:
        self.assertIn("execution_idempotency_key", UP_0005)
        self.assertIn("num_nonnulls(query_id, evaluation_run_id, ingestion_job_id) = 1", UP_0005)
        self.assertIn("parser_profile_id", UP_0005)

    def test_issue45_jobs_and_evaluations_are_correlated(self) -> None:
        self.assertEqual(2, UP_0006.count("ADD COLUMN IF NOT EXISTS correlation_id"))
        self.assertIn("rag_ingestion_job_correlation_idx", UP_0006)
        self.assertIn("rag_evaluation_run_correlation_idx", UP_0006)

    def test_issue46_reindex_fk_is_indexed(self) -> None:
        self.assertIn("rag_code_symbol_chunk_idx", UP_0007)
        self.assertIn("ON rag_code_symbol (chunk_id)", UP_0007)
        self.assertIn("rag_code_relation_to_symbol_idx", UP_0007)
        self.assertIn("ON rag_code_relation (to_symbol_id)", UP_0007)

    def test_community_conversation_separates_turn_response_and_resolution_state(self) -> None:
        self.assertIn("CREATE TABLE IF NOT EXISTS community_turn", UP_0011)
        self.assertIn("CREATE TABLE IF NOT EXISTS community_response", UP_0011)
        self.assertIn("UNIQUE (case_id, source_post_id)", UP_0011)
        for state in ("ANALYZING", "WAITING_REQUESTER", "WAITING_REVIEW", "WAITING_RESOLUTION", "RESOLVED"):
            self.assertIn(f"'{state}'", UP_0011)
        self.assertIn("resolved_by_user_id", UP_0011)

    def test_resolved_conversation_has_knowledge_base_publication_fields(self) -> None:
        for column in (
            "knowledge_base_post_id", "knowledge_base_post_url", "knowledge_base_source_post_id",
            "knowledge_base_answer", "knowledge_base_version", "knowledge_base_published_at",
        ):
            self.assertIn(column, UP_0012)


if __name__ == "__main__":
    unittest.main()
