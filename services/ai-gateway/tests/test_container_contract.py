from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (REPO / "deploy" / "compose" / "ai-gateway" / "compose.yml").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
ARTIFACTS = (ROOT / "app" / "artifacts.py").read_text(encoding="utf-8")


class ContainerContractTest(unittest.TestCase):
    def test_base_image_is_digest_pinned(self) -> None:
        self.assertRegex(DOCKERFILE.splitlines()[0], r"^FROM python:3\.12\.11-slim-bookworm@sha256:[0-9a-f]{64}$")

    def test_runtime_is_non_root(self) -> None:
        self.assertIn("USER 10001:10001", DOCKERFILE)

    def test_git_object_reader_is_installed_without_checkout_workspace(self) -> None:
        self.assertIn("ca-certificates git", DOCKERFILE)
        self.assertIn("TECHFLOW_SOURCE_MIRROR_ROOT: /var/lib/techflow-source-mirrors", COMPOSE)
        self.assertIn("techflow_source_mirrors:/var/lib/techflow-source-mirrors", COMPOSE)
        self.assertNotIn("TECHFLOW_SOURCE_TMPDIR", COMPOSE)

    def test_reconciler_runs_every_six_hours(self) -> None:
        self.assertIn("source-reconciler:", COMPOSE)
        self.assertIn('TECHFLOW_SOURCE_RECONCILE_INTERVAL_SECONDS: "21600"', COMPOSE)
        self.assertIn('["python", "scripts/reconcile_sources.py"]', COMPOSE)

    def test_gateway_is_read_only_and_drops_capabilities(self) -> None:
        gateway = COMPOSE.split("  gateway:", 1)[1].split("\nnetworks:", 1)[0]
        self.assertIn("read_only: true", gateway)
        self.assertIn("cap_drop:", gateway)
        self.assertIn("- ALL", gateway)

    def test_database_network_is_internal(self) -> None:
        self.assertRegex(COMPOSE, r"rag_internal:\n\s+internal: true")

    def test_gateway_has_separate_edge_network(self) -> None:
        gateway = COMPOSE.split("  gateway:", 1)[1].split("\nnetworks:", 1)[0]
        self.assertIn("rag_internal:", gateway)
        self.assertIn("rag_edge:", gateway)
        self.assertIn("ap_automation:", gateway)
        self.assertIn("techflow-ai-gateway", gateway)

    def test_postgres_image_is_digest_pinned(self) -> None:
        self.assertRegex(COMPOSE, r"pgvector/pgvector:pg14@sha256:[0-9a-f]{64}")

    def test_secrets_use_operator_files(self) -> None:
        self.assertEqual(4, len(re.findall(r"file: \$\{TECHFLOW_RAG_[A-Z_]+:\?", COMPOSE)))

    def test_real_openai_key_is_not_configured(self) -> None:
        self.assertNotIn("OPENAI_API_KEY", COMPOSE)
        self.assertIn("TECHFLOW_RAG_PROVIDER_MODE: mock", COMPOSE)

    def test_official_web_search_is_operator_controlled_and_disabled_by_default(self) -> None:
        self.assertIn("TECHFLOW_OFFICIAL_WEB_SEARCH_ENABLED: ${TECHFLOW_OFFICIAL_WEB_SEARCH_ENABLED:-false}", COMPOSE)

    def test_healthcheck_exists(self) -> None:
        self.assertGreaterEqual(COMPOSE.count("healthcheck:"), 2)

    def test_tree_sitter_parsers_are_prefetched_in_the_image(self) -> None:
        self.assertIn("scripts/prefetch_parsers.py", DOCKERFILE)
        self.assertIn("TECHFLOW_TREE_SITTER_CACHE", DOCKERFILE)

    def test_large_artifacts_use_streaming_and_separate_archive_boundary(self) -> None:
        self.assertIn("request.stream()", MAIN)
        self.assertNotIn("await request.body()", MAIN)
        self.assertIn("async def put_stream", ARTIFACTS)
        self.assertIn("TECHFLOW_ARTIFACT_MAX_ARCHIVE_BYTES", COMPOSE)
        self.assertIn("TECHFLOW_COMMUNITY_ARCHIVE_MAX_BYTES", COMPOSE)


if __name__ == "__main__":
    unittest.main()
