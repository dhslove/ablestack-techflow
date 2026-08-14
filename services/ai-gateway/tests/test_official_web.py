from __future__ import annotations

from datetime import datetime, timezone
import unittest

from app.official_web import (
    OFFICIAL_WEB_ALLOWED_DOMAINS,
    allowed_domains_for_question,
    official_web_query,
    official_web_results,
    official_web_search_required,
    support_family,
)


class OfficialWebPolicyTest(unittest.TestCase):
    def test_guest_os_uses_fresh_exact_local_reference_without_web(self) -> None:
        local = [{"sourceKind": "OFFICIAL_EXTERNAL_DOCUMENTATION", "symbol": "Ubuntu 24.04 설치"}]
        question = "Ubuntu에서 qemu-guest-agent를 설치하는 방법을 알려주세요."
        self.assertFalse(official_web_search_required(question, local, stale=False))
        self.assertTrue(official_web_search_required(question, local, stale=True))

    def test_product_names_expand_only_in_private_query(self) -> None:
        cases = (
            ("Glue OSD가 down입니다.", "GLUE", "official Ceph"),
            ("Koral Pod가 시작되지 않습니다.", "KORAL", "official Kubernetes"),
            ("Wall 대시보드가 비어 있습니다.", "WALL", "official Grafana"),
            ("Mold 가상머신 배포가 실패합니다.", "MOLD", "official Apache CloudStack"),
        )
        for question, family, upstream in cases:
            with self.subTest(family=family):
                self.assertEqual(family, support_family(question))
                self.assertIn(upstream, official_web_query(question))
                self.assertTrue(official_web_search_required(question, [], stale=False))
        self.assertIn("libvirt/QEMU/KVM", official_web_query("Mold 콘솔 연결이 실패합니다."))
        self.assertEqual(("docs.ceph.com",), allowed_domains_for_question("Glue OSD가 down입니다."))
        self.assertEqual(("kubernetes.io",), allowed_domains_for_question("Koral Pod가 Pending입니다."))
        self.assertEqual(("grafana.com",), allowed_domains_for_question("Wall 대시보드 오류입니다."))
        self.assertIn("libvirt.org", allowed_domains_for_question("Mold 가상머신 콘솔 오류입니다."))

    def test_only_tool_verified_official_sources_become_context(self) -> None:
        facts = [
            {"statement": "Show cluster health.", "title": "Ceph health", "url": "https://docs.ceph.com/en/latest/rados/operations/health-checks/"},
            {"statement": "Untrusted.", "title": "Blog", "url": "https://example.com/post"},
        ]
        results = official_web_results(
            facts,
            ["https://docs.ceph.com/en/latest/rados/operations/health-checks/", "https://example.com/post"],
            fetched_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(1, len(results))
        self.assertEqual("OFFICIAL_LIVE_WEB_DOCUMENTATION", results[0]["sourceKind"])
        self.assertEqual("2026-08-14T00:00:00+00:00", results[0]["fetchedAt"])
        self.assertIn("docs.ceph.com", OFFICIAL_WEB_ALLOWED_DOMAINS)
        self.assertIn("kubernetes.io", OFFICIAL_WEB_ALLOWED_DOMAINS)
        self.assertIn("grafana.com", OFFICIAL_WEB_ALLOWED_DOMAINS)
        self.assertIn("docs.cloudstack.apache.org", OFFICIAL_WEB_ALLOWED_DOMAINS)

    def test_private_search_query_redacts_identifiers_and_secrets(self) -> None:
        query = official_web_query(
            "Mold 10.10.1.10 오류, admin@example.com token=secret-value, https://internal.example/log"
        )
        self.assertNotIn("10.10.1.10", query)
        self.assertNotIn("admin@example.com", query)
        self.assertNotIn("secret-value", query)
        self.assertNotIn("internal.example", query)


if __name__ == "__main__":
    unittest.main()
