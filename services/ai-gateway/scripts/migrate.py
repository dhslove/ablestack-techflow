#!/usr/bin/env python3
"""Apply or roll back the TechFlow AI Gateway schema without printing credentials."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
EXPECTED_TABLES = {
    "rag_source", "rag_source_version", "rag_compatibility_set", "rag_compatibility_set_source",
    "rag_ingestion_job", "rag_chunk", "rag_embedding_profile", "rag_chunk_embedding",
    "rag_code_symbol", "rag_code_relation", "rag_deletion_ledger", "rag_evaluation_case",
    "rag_evaluation_run", "rag_evaluation_result", "rag_provider_call",
    "rag_source_blob", "rag_source_file", "rag_source_scan_finding",
    "rag_source_mirror", "community_case", "community_case_event", "chat_reviewer_identity",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("direction", choices=("up", "down", "verify"))
    parser.add_argument("--allow-destructive-rollback", action="store_true")
    return parser.parse_args()


def dsn() -> str:
    value = os.getenv("TECHFLOW_RAG_MIGRATION_DSN") or os.getenv("TECHFLOW_RAG_DATABASE_DSN")
    if not value:
        raise SystemExit("migration DSN is required through runtime environment injection")
    return value


def table_names(connection: psycopg.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND "
        "(tablename LIKE 'rag_%' OR tablename LIKE 'community_%' OR tablename LIKE 'chat_%')"
    ).fetchall()
    return {row[0] for row in rows}


def verify(connection: psycopg.Connection) -> None:
    actual = table_names(connection)
    if actual != EXPECTED_TABLES:
        raise SystemExit(f"schema mismatch expected={len(EXPECTED_TABLES)} actual={len(actual)}")
    extensions = {row[0] for row in connection.execute(
        "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')"
    ).fetchall()}
    if extensions != {"vector", "pg_trgm"}:
        raise SystemExit("required extensions are missing")
    profile_count = connection.execute(
        "SELECT count(*) FROM rag_source WHERE source_profile_id IN "
        "('SHARED_DOCS','CLOUD_MAIN','CLOUD_DIPLO','CLOUD_EUROPA','WALL_MAIN','COCKPIT_DIPLO','GENIE_MASTER','KICKSTART_MASTER','QEMU_EXEC_TOOLS_MAIN')"
    ).fetchone()[0]
    if profile_count != 9:
        raise SystemExit(f"source profile registry mismatch expected=9 actual={profile_count}")
    issue43_columns = connection.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND "
        "((table_name='rag_chunk' AND column_name IN ('parser_profile_id','chunk_index','token_count')) OR "
        "(table_name='rag_ingestion_job' AND column_name IN ('execution_idempotency_key','started_at','completed_at','metrics')) OR "
        "(table_name='rag_provider_call' AND column_name='ingestion_job_id'))"
    ).fetchone()[0]
    if issue43_columns != 8:
        raise SystemExit(f"Issue 43 schema mismatch expected=8 actual={issue43_columns}")
    issue45_columns = connection.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND "
        "table_name IN ('rag_ingestion_job','rag_evaluation_run') AND column_name='correlation_id'"
    ).fetchone()[0]
    if issue45_columns != 2:
        raise SystemExit(f"Issue 45 schema mismatch expected=2 actual={issue45_columns}")
    issue46_indexes = connection.execute(
        "SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND "
        "indexname IN ('rag_code_symbol_chunk_idx','rag_code_relation_to_symbol_idx')"
    ).fetchone()[0]
    if issue46_indexes != 2:
        raise SystemExit(f"Issue 46 schema mismatch expectedIndexes=2 actual={issue46_indexes}")
    community_tables = connection.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename IN ('community_case','community_case_event')"
    ).fetchone()[0]
    if community_tables != 2:
        raise SystemExit(f"Issue 21 schema mismatch expectedTables=2 actual={community_tables}")
    chat_tables = connection.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename='chat_reviewer_identity'"
    ).fetchone()[0]
    if chat_tables != 1:
        raise SystemExit(f"Issue 22 schema mismatch expectedTables=1 actual={chat_tables}")
    issue64_columns = connection.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND "
        "table_name='community_case' AND column_name IN ('review_post_id','review_post_url')"
    ).fetchone()[0]
    if issue64_columns != 2:
        raise SystemExit(f"Issue 64 schema mismatch expectedColumns=2 actual={issue64_columns}")
    print(f"schema=valid tables={len(EXPECTED_TABLES)} extensions=2 sourceProfiles=9 "
          "issue43Columns=8 issue45Columns=2 issue46Indexes=2 issue21Tables=2 issue22Tables=1 issue64Columns=2")


def main() -> int:
    args = parse_args()
    with psycopg.connect(dsn(), autocommit=False) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(82410042)")
        if args.direction == "verify":
            verify(connection)
            return 0
        if args.direction == "down":
            if not args.allow_destructive_rollback:
                raise SystemExit("--allow-destructive-rollback is required")
            issue22_present = connection.execute(
                "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='chat_reviewer_identity'"
            ).fetchone()
            issue64_present = connection.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name='community_case' AND column_name='review_post_id'"
            ).fetchone()
            if issue64_present:
                connection.execute((MIGRATIONS / "0010_flarum_review_post_down.sql").read_text(encoding="utf-8"))
            if issue22_present:
                connection.execute((MIGRATIONS / "0009_chat_approval_down.sql").read_text(encoding="utf-8"))
            issue21_present = connection.execute(
                "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='community_case'"
            ).fetchone()
            if issue21_present:
                connection.execute((MIGRATIONS / "0008_community_assist_down.sql").read_text(encoding="utf-8"))
            issue46_present = connection.execute(
                "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND "
                "indexname IN ('rag_code_symbol_chunk_idx','rag_code_relation_to_symbol_idx')"
            ).fetchone()
            if issue46_present:
                connection.execute((MIGRATIONS / "0007_reindex_fk_performance_down.sql").read_text(encoding="utf-8"))
            issue45_present = connection.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name='rag_ingestion_job' AND column_name='correlation_id'"
            ).fetchone()
            if issue45_present:
                connection.execute((MIGRATIONS / "0006_orchestration_correlation_down.sql").read_text(encoding="utf-8"))
            issue43_present = connection.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name='rag_ingestion_job' AND column_name='metrics'"
            ).fetchone()
            if issue43_present:
                connection.execute((MIGRATIONS / "0005_parser_embedding_retrieval_down.sql").read_text(encoding="utf-8"))
            if "rag_source_mirror" in table_names(connection):
                connection.execute((MIGRATIONS / "0004_source_mirror_policy_down.sql").read_text(encoding="utf-8"))
                connection.execute((MIGRATIONS / "0003_source_mirror_down.sql").read_text(encoding="utf-8"))
            if "rag_source_blob" in table_names(connection):
                connection.execute((MIGRATIONS / "0002_source_registry_down.sql").read_text(encoding="utf-8"))
            connection.execute((MIGRATIONS / "0001_schema_down.sql").read_text(encoding="utf-8"))
            print("schema=rolled-back")
            return 0
        connection.execute((MIGRATIONS / "0000_extensions_roles_up.sql").read_text(encoding="utf-8"))
        actual = table_names(connection)
        if not actual:
            connection.execute((MIGRATIONS / "0001_schema_up.sql").read_text(encoding="utf-8"))
        if "rag_source_blob" not in table_names(connection):
            connection.execute((MIGRATIONS / "0002_source_registry_up.sql").read_text(encoding="utf-8"))
        if "rag_source_mirror" not in table_names(connection):
            connection.execute((MIGRATIONS / "0003_source_mirror_up.sql").read_text(encoding="utf-8"))
        connection.execute((MIGRATIONS / "0004_source_mirror_policy_up.sql").read_text(encoding="utf-8"))
        issue43_present = connection.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='rag_ingestion_job' AND column_name='metrics'"
        ).fetchone()
        if not issue43_present:
            connection.execute((MIGRATIONS / "0005_parser_embedding_retrieval_up.sql").read_text(encoding="utf-8"))
        issue45_present = connection.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='rag_ingestion_job' AND column_name='correlation_id'"
        ).fetchone()
        if not issue45_present:
            connection.execute((MIGRATIONS / "0006_orchestration_correlation_up.sql").read_text(encoding="utf-8"))
        connection.execute((MIGRATIONS / "0007_reindex_fk_performance_up.sql").read_text(encoding="utf-8"))
        connection.execute((MIGRATIONS / "0008_community_assist_up.sql").read_text(encoding="utf-8"))
        connection.execute((MIGRATIONS / "0009_chat_approval_up.sql").read_text(encoding="utf-8"))
        connection.execute((MIGRATIONS / "0010_flarum_review_post_up.sql").read_text(encoding="utf-8"))
        verify(connection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
