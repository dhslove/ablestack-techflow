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
    support_topic,
)
from app.platform_references import curated_platform_results


class OfficialWebPolicyTest(unittest.TestCase):
    def test_guest_os_uses_fresh_exact_local_reference_without_web(self) -> None:
        local = [{
            "sourceKind": "OFFICIAL_EXTERNAL_DOCUMENTATION",
            "symbol": "Ubuntu 24.04 QEMU Guest Agent 설치",
            "content": "qemu-guest-agent 공식 패키지 설치 절차",
        }]
        question = "Ubuntu에서 qemu-guest-agent를 설치하는 방법을 알려주세요."
        self.assertFalse(official_web_search_required(question, local, stale=False))
        self.assertTrue(official_web_search_required(question, local, stale=True))

    def test_windows_time_question_uses_exact_microsoft_evidence_or_live_fallback(self) -> None:
        question = (
            "Windows Server 2022 가상머신에서 시간이 잘 안맞아. NTP 설정 방법과 PowerShell 강제 동기화, "
            "확인 방법을 알려줘."
        )
        local = curated_platform_results(question)

        self.assertEqual("WINDOWS", support_family(question))
        self.assertEqual("TIME_SYNC", support_topic(question))
        self.assertEqual(("learn.microsoft.com",), allowed_domains_for_question(question))
        self.assertIn("Microsoft Learn", official_web_query(question))
        self.assertFalse(official_web_search_required(question, local, stale=False))
        self.assertTrue(official_web_search_required(question, [], stale=False))
        self.assertTrue(any("w32tm /resync /rediscover" in item["content"] for item in local))
        self.assertFalse(any("QEMU Guest Agent" in item["symbol"] for item in local))

    def test_general_guest_os_procedure_requires_domain_restricted_official_search(self) -> None:
        question = "Windows Server 2022 가상머신에서 DNS 설정을 확인하는 PowerShell 방법을 알려줘."

        self.assertEqual("GENERAL_OS", support_topic(question))
        self.assertTrue(official_web_search_required(question, [], stale=False))
        self.assertEqual(("learn.microsoft.com",), allowed_domains_for_question(question))

    def test_additional_guest_os_families_use_only_their_official_domains(self) -> None:
        cases = (
            ("Debian 12에서 디스크 마운트 방법", "DEBIAN", ("docs.debian.org", "manpages.debian.org")),
            ("openSUSE에서 NFS 설정 방법", "SUSE", ("documentation.suse.com",)),
            ("Fedora에서 방화벽 확인 방법", "FEDORA", ("docs.fedoraproject.org",)),
            ("Oracle Linux에서 디스크 마운트 방법", "ORACLE_LINUX", ("docs.oracle.com",)),
            ("FreeBSD에서 서비스 확인 방법", "FREEBSD", ("docs.freebsd.org", "man.freebsd.org")),
            ("Alpine Linux에서 패키지 설치 방법", "ALPINE", ("docs.alpinelinux.org",)),
            ("Arch Linux에서 SMB 설정 방법", "ARCH", ("wiki.archlinux.org",)),
            ("Amazon Linux에서 디스크 확인 방법", "AMAZON_LINUX", ("docs.aws.amazon.com",)),
            ("Kali Linux에서 네트워크 확인 방법", "KALI", ("docs.kali.org",)),
            ("Solaris에서 NFS 마운트 방법", "SOLARIS", ("docs.oracle.com",)),
            ("AIX에서 파일시스템 확인 방법", "AIX", ("www.ibm.com",)),
            ("macOS 가상머신에서 DNS 확인 방법", "MACOS", ("support.apple.com",)),
        )
        for question, family, domains in cases:
            with self.subTest(family=family):
                self.assertEqual(family, support_family(question))
                self.assertEqual("GENERAL_OS", support_topic(question))
                self.assertEqual(domains, allowed_domains_for_question(question))
                self.assertTrue(official_web_search_required(question, [], stale=False))

    def test_unknown_linux_distribution_uses_bounded_official_catalog_without_guessing_product_logs(self) -> None:
        question = "ExampleOS Linux 가상머신에서 SMB 마운트 방법을 알려주세요."

        self.assertEqual("GENERIC_LINUX", support_family(question))
        self.assertEqual("SMB_MOUNT", support_topic(question))
        domains = allowed_domains_for_question(question)
        self.assertIn("docs.redhat.com", domains)
        self.assertIn("docs.debian.org", domains)
        self.assertNotIn("example.com", domains)
        self.assertTrue(official_web_search_required(question, [], stale=False))

    def test_smb_mount_search_requires_topic_specific_official_evidence(self) -> None:
        question = "Debian 12에서 SMB 공유 폴더를 마운트하는 명령을 알려주세요."

        self.assertEqual("SMB_MOUNT", support_topic(question))
        self.assertIn("mount.cifs", official_web_query(question))
        irrelevant = [{
            "sourceKind": "OFFICIAL_EXTERNAL_DOCUMENTATION",
            "symbol": "Debian apt-get",
            "content": "apt-get package manager",
        }]
        self.assertTrue(official_web_search_required(question, irrelevant, stale=False))

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
