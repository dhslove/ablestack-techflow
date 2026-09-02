from __future__ import annotations

import json
from pathlib import Path
import unittest

from app.versioned_assist import (
    CURATED_PLATFORM_PROFILE,
    CURRENT_SOURCE_PROFILES,
    INTERNAL_REFERENCE_ONLY_PROFILE,
    PREVIEW_SOURCE_PROFILE,
    VERSIONED_SOURCE_PROFILES,
    coverage_payload,
    evidence_priority,
    expand_retrieval_question,
    feature_source_terms,
    format_public_answer,
    format_knowledge_base,
    projection_is_safe,
    relevant_results,
    implementation_identifiers,
    sanitize_public_text,
    simplify_public_text,
    select_context_results,
    versioned_plan,
)
from app.platform_references import curated_platform_results


class VersionedAssistPolicyTest(unittest.TestCase):
    def test_plan_reviews_docs_diplo_related_code_and_europa_preview(self) -> None:
        plan = versioned_plan("VM 배포가 실패합니다")
        self.assertEqual(list(VERSIONED_SOURCE_PROFILES), plan["sourceProfileIds"])
        self.assertIn("SHARED_DOCS", CURRENT_SOURCE_PROFILES)
        self.assertIn("CLOUD_DIPLO", CURRENT_SOURCE_PROFILES)
        self.assertEqual("CLOUD_EUROPA", PREVIEW_SOURCE_PROFILE)
        self.assertIn(CURATED_PLATFORM_PROFILE, plan["sourceProfileIds"])
        self.assertNotIn(INTERNAL_REFERENCE_ONLY_PROFILE, plan["sourceProfileIds"])

    def test_coverage_records_every_reviewed_profile(self) -> None:
        coverage = coverage_payload("VM 배포 오류", {
            "SHARED_DOCS": [{"chunkId": "1", "content": "VM 배포 절차", "path": "guide.md"}],
            "CLOUD_DIPLO": [],
        })
        self.assertEqual(len(VERSIONED_SOURCE_PROFILES), len(coverage))
        self.assertEqual("EVIDENCE_FOUND", coverage[0]["state"])
        self.assertEqual("NO_RELEVANT_EVIDENCE", coverage[1]["state"])

    def test_console_connecting_question_expands_retrieval_vocabulary(self) -> None:
        question = "Mold 콘솔 화면이 연결중에서 멈춥니다."
        expanded = expand_retrieval_question(question)
        self.assertIn(question, expanded)
        self.assertIn("consoleproxy", expanded)
        self.assertIn("websockify", expanded)
        self.assertIn("VNC".casefold(), expanded.casefold())

    def test_console_connecting_question_prioritizes_console_proxy_evidence(self) -> None:
        question = "가상머신 콘솔 화면이 연결중이라고 표시됩니다."
        rows = [
            {"path": "ui/src/GenericVm.vue", "content": "가상머신 화면 표시"},
            {"path": "systemvm/agent/noVNC/vnc_lite.html", "content": "Connecting websocket websockify VNC"},
            {"path": "docs/systemvm.md", "content": "Console Proxy VM and noVNC console"},
        ]
        ranked = relevant_results(question, rows)
        self.assertEqual("systemvm/agent/noVNC/vnc_lite.html", ranked[0]["path"])

    def test_fsfreeze_permission_question_expands_retrieval_vocabulary(self) -> None:
        question = "새 디스크를 /mnt에 연결한 뒤 스냅샷에서 guest-fsfreeze-freeze Permission denied가 발생합니다."
        expanded = expand_retrieval_question(question)
        self.assertIn("qemu-guest-agent", expanded)
        self.assertIn("ausearch", expanded)
        self.assertIn("matchpathcon", expanded)
        self.assertIn("restorecon", expanded)

    def test_fsfreeze_retrieval_expansion_stays_within_query_limit(self) -> None:
        question = ("guest-fsfreeze-freeze Permission denied /mnt " + ("긴 대화 " * 800))[:4000]

        expanded = expand_retrieval_question(question)

        self.assertLessEqual(len(expanded), 4000)
        self.assertTrue(expanded.startswith("guest-fsfreeze-freeze Permission denied /mnt"))
        self.assertIn("진단 검색어:", expanded)
        self.assertIn("restorecon", expanded)

    def test_korean_retrieval_expansion_uses_utf8_byte_limit(self) -> None:
        question = "Mold 네트워크 생성 요청 실패 " + "한글 대화 문맥 " * 1200

        expanded = expand_retrieval_question(question)

        self.assertLessEqual(len(expanded.encode("utf-8")), 4000)
        self.assertTrue(expanded.startswith("Mold 네트워크 생성 요청 실패"))
        self.assertIn("진단 검색어:", expanded)
        self.assertIn("createNetwork", expanded)

    def test_fsfreeze_question_loads_safe_local_platform_guidance(self) -> None:
        question = "새 볼륨을 /mnt에 마운트한 뒤 guest-fsfreeze-freeze Permission denied가 발생합니다."
        results = curated_platform_results(question)
        combined = "\n".join(item["content"] for item in results)
        self.assertGreaterEqual(len(results), 2)
        self.assertIn("sudo ausearch", combined)
        self.assertIn("sudo findmnt", combined)
        self.assertIn("sudo restorecon", combined)
        self.assertIn("SELinux 전체 비활성화", combined)
        self.assertNotIn("setenforce 0", combined)

    def test_guest_agent_question_loads_exact_guest_os_commands(self) -> None:
        cases = (
            ("Ubuntu 24.04 qemu-guest-agent 설치 방법", "sudo apt install -y qemu-guest-agent"),
            ("Rocky Linux qemu-guest-agent 설치 방법", "sudo dnf install -y qemu-guest-agent"),
            ("Windows qemu guest agent 설치 방법", "Get-Service QEMU-GA"),
        )
        for question, expected in cases:
            with self.subTest(question=question):
                combined = "\n".join(item["content"] for item in curated_platform_results(question))
                self.assertIn(expected, combined)

    def test_windows_server_time_question_loads_only_matching_official_time_guidance(self) -> None:
        question = "Windows Server 2022 가상머신 NTP 설정과 PowerShell 강제 시간 동기화 방법"
        expanded = expand_retrieval_question(question)
        results = curated_platform_results(question)
        combined = "\n".join(item["content"] for item in results)

        for expected in (
            "W32Time", "w32tm /query /source", "syncfromflags:domhier", "manualpeerlist",
            "w32tm /resync /rediscover", "w32tm /stripchart", "UDP 123",
        ):
            self.assertIn(expected, combined)
        self.assertIn("Get-TimeZone", expanded)
        self.assertIn("rediscover", expanded)
        self.assertNotIn("qemu-ga-x86_64.msi", combined)

    def test_kvm_ha_degraded_guidance_has_exact_targets_services_and_logs(self) -> None:
        question = (
            "BMC 활성화 후 HA 공급자 kvmhapervider는 오타이고 kvmhaprovider가 맞습니다. "
            "호스트 HA 상태가 Suspect에서 Degraded로 바뀌었습니다."
        )
        combined = "\n".join(item["content"] for item in curated_platform_results(question))

        for expected in (
            "kvmhaprovider", "Activity Check", "kvm.ha.on.storage.heartbeat", "HA.STATE.TRANSITION",
            "ssh -p <SSH_PORT>", "mold.service", "mold-agent.service",
            "/var/log/cloudstack/management/management-server.log",
            "/var/log/cloudstack/agent/agent.log", "--since", "--until", "마스킹",
        ):
            self.assertIn(expected, combined)
        self.assertIn("Degraded를 libvirt 장애 하나로 단정하지 않는다", combined)
        self.assertIn("Available 전에는 호스트 전원 차단", combined)

    def test_rocky_linux_smb_question_loads_exact_official_mount_procedure(self) -> None:
        question = (
            "Rocky Linux 8.10 가상머신에서 SMB 서버에 연결해서 마운트하고 싶습니다. "
            "마운트 방법을 명령어로 알려주세요."
        )
        results = curated_platform_results(question)
        combined = "\n".join(item["content"] for item in results)

        for expected in (
            "sudo dnf install -y cifs-utils", "sudo mkdir -p /mnt/smb", "mount -t cifs",
            "credentials=/root/smb.cred", "sudo chmod 600", "sudo mount -a", "findmnt -T /mnt/smb",
        ):
            self.assertIn(expected, combined)
        self.assertTrue(any("docs.redhat.com" in item["path"] for item in results))
        self.assertNotIn("qemu-ga-x86_64.msi", combined)

    def test_windows_time_inline_commands_render_as_powershell(self) -> None:
        answer = format_public_answer({
            "state": "ANSWERED",
            "report": {
                "summary": "Windows 시간 원본을 확인합니다.",
                "observedFacts": [], "diagnoses": [],
                "recommendedActions": [
                    "관리자 PowerShell에서 `w32tm /query /source`와 `w32tm /resync /rediscover`를 실행합니다."
                ],
                "unknowns": [], "currentAssessment": "CURRENT_CONFIG_ERROR",
                "previewAssessment": "NOT_APPLICABLE", "previewGuidance": None,
            },
            "citations": [],
        }) or ""

        self.assertIn("```powershell\nw32tm /query /source\nw32tm /resync /rediscover\n```", answer)
        self.assertIn("관리자 PowerShell에서 아래 명령을 실행합니다.", answer)
        self.assertNotIn("다음 명령과 다음 명령", answer)

    def test_incomplete_windows_stripchart_is_rendered_as_a_copyable_check(self) -> None:
        answer = format_public_answer({
            "state": "ANSWERED",
            "report": {
                "summary": "NTP 응답을 확인합니다.", "observedFacts": [], "diagnoses": [],
                "recommendedActions": ["관리자 PowerShell에서 `w32tm /stripchart`를 실행합니다."],
                "unknowns": [], "currentAssessment": "CURRENT_CONFIG_ERROR",
                "previewAssessment": "NOT_APPLICABLE", "previewGuidance": None,
            },
            "citations": [],
        }) or ""

        self.assertIn(
            "w32tm /stripchart /computer:<NTP_SERVER> /dataonly /samples:5",
            answer,
        )

    def test_glue_koral_and_wall_expand_to_upstream_terms(self) -> None:
        self.assertIn("ceph health detail", expand_retrieval_question("Glue 상태가 WARN입니다."))
        self.assertIn("kubernetes", expand_retrieval_question("Koral Pod가 시작되지 않습니다."))
        self.assertIn("grafana-server", expand_retrieval_question("Wall 대시보드가 비어 있습니다."))
        self.assertIn("cloudstack api", expand_retrieval_question("Mold 가상머신 배포가 실패합니다."))
        self.assertIn("libvirt", expand_retrieval_question("Mold 가상머신 콘솔이 연결되지 않습니다."))

    def test_network_request_failure_maps_feature_to_current_source_symbols(self) -> None:
        question = '네트워크를 만들 때 "요청 실패"가 표시됩니다.'

        terms = feature_source_terms(question)
        expanded = expand_retrieval_question(question)
        plan = versioned_plan(question)

        for expected in (
            "createNetwork", "CreateNetworkCmd", "NetworkServiceImpl", "ApiErrorCode",
            "SamlDomainSwitcher", "listAndSwitchSamlAccount", "HTTP 432",
        ):
            self.assertIn(expected, terms)
            self.assertIn(expected, expanded)
            self.assertIn(expected, plan["featureSourceTerms"])

        self.assertIn("CreateNetworkCmd", implementation_identifiers(expanded))
        self.assertIn("SamlDomainSwitcher", implementation_identifiers(expanded))

    def test_network_request_failure_prioritizes_api_and_ui_source_over_generic_network_text(self) -> None:
        question = '네트워크 생성 중 요청 실패가 발생하고 화면에는 HTTP 432가 보입니다.'
        rows = [
            {"path": "docs/network.md", "content": "일반 네트워크 안내"},
            {"path": "api/src/ApiErrorCode.java", "content": "UNSUPPORTED_ACTION_ERROR(432)"},
            {"path": "ui/src/components/header/SamlDomainSwitcher.vue", "content": "listAndSwitchSamlAccount"},
            {"path": "api/src/CreateNetworkCmd.java", "content": "createNetwork physicalNetworkId networkOfferingId"},
        ]

        ranked = relevant_results(question, rows)

        self.assertEqual("api/src/CreateNetworkCmd.java", ranked[0]["path"])
        self.assertEqual(
            {
                "api/src/ApiErrorCode.java",
                "ui/src/components/header/SamlDomainSwitcher.vue",
                "api/src/CreateNetworkCmd.java",
            },
            {item["path"] for item in ranked[:3]},
        )

    def test_network_request_failure_keeps_create_api_error_and_background_ui_context(self) -> None:
        question = '네트워크 생성 중 요청 실패가 발생하고 화면에는 HTTP 432가 보입니다.'
        current_rows = [
            {"path": "api/src/CreateNetworkCmd.java", "content": "createNetwork physicalNetworkId"},
            {"path": "server/src/NetworkServiceImpl.java", "content": "networkOfferingId guestType specifyVlan"},
            {"path": "api/src/ApiErrorCode.java", "content": "UNSUPPORTED_ACTION_ERROR(432)"},
            {"path": "server/src/ApiServer.java", "content": "Unknown API command unsupported action"},
            {"path": "ui/src/SamlDomainSwitcher.vue", "content": "listAndSwitchSamlAccount"},
            {"path": "ui/src/request.js", "content": "x-description errortext"},
            {"path": "docs/generic-network.md", "content": "network"},
        ]

        selected = select_context_results(question, {"CLOUD_DIPLO": current_rows})

        selected_paths = {item["path"] for item in selected}
        self.assertEqual(6, len(selected))
        self.assertIn("api/src/CreateNetworkCmd.java", selected_paths)
        self.assertIn("api/src/ApiErrorCode.java", selected_paths)
        self.assertIn("ui/src/SamlDomainSwitcher.vue", selected_paths)

    def test_live_official_source_has_platform_priority(self) -> None:
        self.assertEqual(
            (3, "OFFICIAL_PLATFORM_DOCUMENTATION"),
            evidence_priority(CURATED_PLATFORM_PROFILE, "OFFICIAL_LIVE_WEB_DOCUMENTATION"),
        )

    def test_console_context_includes_multiple_docs_and_current_code_chunks(self) -> None:
        question = "Mold 콘솔 화면이 연결중에서 멈춥니다."
        rows = [{"path": f"consoleproxy/{index}.java", "content": "noVNC websockify VNC"} for index in range(6)]
        selected = select_context_results(question, {
            "SHARED_DOCS": rows,
            "CLOUD_DIPLO": rows,
            CURATED_PLATFORM_PROFILE: curated_platform_results(question),
            "CLOUD_EUROPA": rows,
        })
        self.assertEqual(13, len(selected))
        self.assertEqual(4, sum(item.get("sourceProfileId") == CURATED_PLATFORM_PROFILE for item in selected))

    def test_console_question_loads_only_local_approved_platform_references(self) -> None:
        question = "Mold 콘솔 화면이 연결중 상태입니다."
        results = curated_platform_results(question)
        self.assertEqual(4, len(results))
        self.assertTrue(all(item["sourceProfileId"] == CURATED_PLATFORM_PROFILE for item in results))
        self.assertTrue(any(item["sourceKind"] == "OPERATOR_APPROVED_KNOWLEDGE" for item in results))
        self.assertTrue(any("query-vnc" in item["content"] for item in results))
        self.assertTrue(any("라이브 마이그레이션" in item["content"] for item in results))
        self.assertEqual([], curated_platform_results("사용자 계정 이름을 변경하는 방법"))

    def test_runtime_issue_public_projection_does_not_expose_reference_locator(self) -> None:
        citation = curated_platform_results("Mold 콘솔 화면이 연결중 상태입니다.")[0]
        result = {
            "state": "ANSWERED",
            "report": {
                "summary": "콘솔은 연결중이지만 게스트 서비스는 동작합니다.",
                "observedFacts": [],
                "diagnoses": [{"title": "QEMU VNC 세션 상태 문제"}],
                "recommendedActions": ["sudo virsh qemu-monitor-command <VM> --pretty query-vnc로 확인합니다."],
                "unknowns": [],
                "currentAssessment": "CURRENT_RUNTIME_ISSUE",
                "previewAssessment": "NOT_APPLICABLE",
                "previewGuidance": None,
            },
            "citations": [citation],
        }
        answer = format_public_answer(result) or ""
        self.assertIn("가상화 프로그램이 일시적으로 정상 상태를 잃은 문제", answer)
        self.assertNotIn("operator://", answer)
        self.assertNotIn("sourceLocator", answer)
        self.assertTrue(projection_is_safe(answer), answer)

    def test_ongoing_answer_places_solution_before_reason_and_fallback(self) -> None:
        result = {
            "state": "ANSWERED",
            "report": {
                "summary": "새 마운트 지점의 권한을 먼저 확인하겠습니다.",
                "observedFacts": [],
                "diagnoses": [{"title": "SELinux 문맥 또는 일반 권한이 접근을 막았을 수 있습니다."}],
                "recommendedActions": ["게스트에서 `sudo ausearch -m AVC,USER_AVC -ts recent`를 실행합니다."],
                "unknowns": ["명령 출력과 qemu-guest-agent 로그를 알려주세요."],
                "currentAssessment": "INSUFFICIENT_EVIDENCE",
                "previewAssessment": "NOT_APPLICABLE",
                "previewGuidance": None,
            },
            "citations": [],
        }
        answer = format_public_answer(result) or ""
        solution = answer.index("먼저 다음 해결 방법을 적용해 보세요.")
        reason = answer.index("이 방법을 먼저 권장하는 이유는 다음과 같습니다.")
        fallback = answer.index("위 조치로 해결되지 않으면 아래 결과를 알려주세요.")
        self.assertLess(solution, reason)
        self.assertLess(reason, fallback)
        self.assertIn("sudo ausearch", answer)

    def test_public_answer_separates_explanation_and_copyable_cli(self) -> None:
        result = {
            "state": "ANSWERED",
            "report": {
                "summary": "먼저 SELinux 차단 기록을 확인합니다.",
                "observedFacts": [],
                "diagnoses": [],
                "recommendedActions": [
                    "게스트 운영체제에서 `sudo ausearch -m AVC,USER_AVC -ts recent`를 실행합니다."
                ],
                "unknowns": [],
                "currentAssessment": "INSUFFICIENT_EVIDENCE",
                "previewAssessment": "NOT_APPLICABLE",
                "previewGuidance": None,
            },
            "citations": [],
        }
        answer = format_public_answer(result) or ""
        self.assertIn("가상머신 안의 운영체제에서 다음 명령을 실행합니다.", answer)
        self.assertIn("```bash\nsudo ausearch -m AVC,USER_AVC -ts recent\n```", answer)

    def test_public_answer_uses_powershell_fence_for_windows_commands(self) -> None:
        result = {
            "state": "ANSWERED",
            "report": {
                "summary": "Windows 게스트 에이전트를 확인합니다.", "observedFacts": [], "diagnoses": [],
                "recommendedActions": ["관리자 PowerShell에서 `Get-Service QEMU-GA`를 실행합니다."],
                "unknowns": [], "currentAssessment": "INSUFFICIENT_EVIDENCE",
                "previewAssessment": "NOT_APPLICABLE", "previewGuidance": None,
            },
            "citations": [],
        }
        answer = format_public_answer(result) or ""
        self.assertIn("```powershell\nGet-Service QEMU-GA\n```", answer)
        self.assertNotIn("`sudo ausearch", answer)

    def test_public_projection_removes_all_external_urls(self) -> None:
        answer = sanitize_public_text(
            "공식 자료 https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html 를 확인합니다.",
        )
        self.assertNotIn("https://", answer)
        self.assertIn("내부 검토 자료", answer)

    def test_public_projection_removes_inline_citation_tokens_without_placeholder(self) -> None:
        token = "81e47d5d-d194-5b62-9979-55a767d9a91a"
        answer = sanitize_public_text(
            f"QEMU 상태를 확인합니다. [{token}] 다음 조치를 수행합니다. [{token}]",
            [{"chunkId": token}],
        )
        self.assertEqual("QEMU 상태를 확인합니다. 다음 조치를 수행합니다.", answer)
        self.assertNotIn("내부 근거", answer)

    def test_internal_action_labels_are_removed_from_public_answer(self) -> None:
        rows = [
            (
                "[변경 없음] DB에서 template ID를 직접 수정하지 마십시오.",
                "DB에서 template ID를 직접 수정하지 마십시오.",
            ),
            (
                "[읽기 전용·호스트 관리자] PYHVS5에서 D-Bus 상태를 확인하십시오.",
                "서버 관리자는 PYHVS5에서 D-Bus 상태를 확인하십시오.",
            ),
            (
                "[읽기 전용·네트워크 관리자] 원본 호스트에서 대상 포트 연결을 확인하십시오.",
                "네트워크 관리자는 원본 호스트에서 대상 포트 연결을 확인하십시오.",
            ),
            (
                "[읽기 전용] Mold에서 호스트 상태를 확인하십시오.",
                "Mold에서 호스트 상태를 확인하십시오.",
            ),
        ]
        for source, expected in rows:
            with self.subTest(source=source):
                answer = simplify_public_text(source)
                self.assertEqual(expected, answer)
                self.assertNotIn("[", answer)

    def test_user_meaningful_bracket_prefix_is_preserved(self) -> None:
        self.assertEqual(
            "[주의] 서비스가 중단될 수 있습니다.",
            simplify_public_text("[주의] 서비스가 중단될 수 있습니다."),
        )

    def test_public_projection_preserves_safe_guest_agent_channel_path(self) -> None:
        answer = simplify_public_text(
            "`ls -l /dev/virtio-ports/org.qemu.guest_agent.0` 결과를 확인하고 1~2분 뒤 다시 조회하세요."
        )
        self.assertIn("/dev/virtio-ports/org.qemu.guest_agent.0", answer)
        self.assertIn("1–2분", answer)
        self.assertNotIn("제품 내부 경로", answer)

    def test_ongoing_answer_naturalizes_internal_action_labels(self) -> None:
        answer = format_public_answer({
            "state": "ANSWERED",
            "report": {
                "summary": "마이그레이션이 완료되지 않았습니다.",
                "observedFacts": ["가상머신 마이그레이션이 실패했습니다."],
                "diagnoses": [{"title": "현재 로그만으로 원인을 확정하기 어렵습니다."}],
                "recommendedActions": [
                    "[변경 없음] DB에서 template ID를 직접 수정하지 마십시오.",
                    "[읽기 전용·호스트 관리자] PYHVS5에서 D-Bus 상태를 확인하십시오.",
                    "[읽기 전용·네트워크 관리자] 원본 호스트에서 대상 포트 연결을 확인하십시오.",
                ],
                "unknowns": [],
                "currentAssessment": "INSUFFICIENT_EVIDENCE",
                "previewAssessment": "NOT_APPLICABLE",
                "previewGuidance": None,
            },
            "citations": [],
        }) or ""
        self.assertNotIn("[변경 없음]", answer)
        self.assertNotIn("[읽기 전용", answer)
        self.assertIn("DB에서 template ID를 직접 수정하지 마십시오.", answer)
        self.assertIn("서버 관리자는 PYHVS5에서 D-Bus 상태를 확인하십시오.", answer)
        self.assertIn("네트워크 관리자는 원본 호스트에서 대상 포트 연결을 확인하십시오.", answer)

    def test_public_projection_removes_internal_lineage(self) -> None:
        citation = {
            "repository": "ablecloud-team/ablestack-cloud", "branch": "ablestack-diplo",
            "commit": "a" * 40, "path": "server/src/Foo.java", "startLine": 10, "endLine": 20,
            "sourceProfileId": "CLOUD_DIPLO",
        }
        result = {
            "state": "ANSWERED",
            "report": {
                "summary": "ablecloud-team/ablestack-cloud server/src/Foo.java:10에서 확인했습니다.",
                "observedFacts": ["CLOUD_DIPLO 현재 오류"],
                "diagnoses": [{"title": "현재 구현 결함"}],
                "recommendedActions": ["임시 조치를 적용합니다."],
                "unknowns": [],
                "currentAssessment": "CURRENT_DEFECT",
                "previewAssessment": "PREVIEW_IMPROVED",
                "previewGuidance": "github.com/ablecloud-team/ablestack-cloud 에서 개선을 확인했습니다.",
            },
            "citations": [citation],
        }
        answer = format_knowledge_base(result) or ""
        self.assertTrue(projection_is_safe(answer), answer)
        headings = ["### 증상", "### 원인", "### 해결 방법", "### 추가 고려사항", "### 적용 버전"]
        self.assertTrue(all(heading in answer for heading in headings), answer)
        self.assertEqual(sorted(answer.index(heading) for heading in headings), [answer.index(heading) for heading in headings])
        self.assertIn("- ABLESTACK Diplo", answer)
        self.assertNotIn("ABLESTACK Europa", answer)
        self.assertNotIn("개선이 진행 중", answer)
        self.assertNotIn("Foo.java", answer)
        self.assertNotIn("CLOUD_DIPLO", answer)

    def test_public_projection_does_not_replace_branch_name_inside_normal_word(self) -> None:
        answer = sanitize_public_text("DNS Domain Name Suffix를 확인합니다.", [{"branch": "main"}])
        self.assertEqual("DNS Domain Name Suffix를 확인합니다.", answer)

    def test_troubleshooting_sections_remain_when_optional_content_is_empty(self) -> None:
        answer = format_knowledge_base({
            "state": "ANSWERED",
            "report": {
                "summary": "현상을 확인했습니다.", "observedFacts": [], "diagnoses": [],
                "recommendedActions": [], "unknowns": [], "currentAssessment": "CURRENT_NORMAL",
                "previewAssessment": "NOT_APPLICABLE", "previewGuidance": None,
            },
            "citations": [],
        }) or ""
        self.assertIn("현재 근거에서 확인된 원인은 없습니다.", answer)
        self.assertIn("별도의 추가 고려사항은 확인되지 않았습니다.", answer)
        self.assertIn("- ABLESTACK Diplo", answer)
        self.assertNotIn("차기 버전", answer)

    def test_application_version_lists_supported_product_without_internal_preview_assessment(self) -> None:
        answer = format_knowledge_base({
            "state": "ANSWERED",
            "report": {
                "summary": "복제 오류가 발생했습니다.",
                "observedFacts": ["가상머신 복제가 실패했습니다."],
                "diagnoses": [{"title": "SELinux 문맥이 맞지 않습니다."}],
                "recommendedActions": ["restorecon으로 문맥을 복구합니다."],
                "unknowns": [], "artifactEvidence": [],
                "currentAssessment": "CURRENT_CONFIG_ERROR",
                "previewAssessment": "PREVIEW_NOT_FOUND",
                "previewGuidance": "차기 버전 코드에서 개선을 확인하지 못해 제품 보완 검토가 필요합니다.",
            },
            "citations": [],
        }) or ""
        version = answer.split("### 적용 버전", 1)[1]
        self.assertIn("- ABLESTACK Diplo", version)
        for hidden in ("현재 적용 기준", "차기 참고 기준", "ABLESTACK Europa", "제품 보완", "개선을 확인"):
            self.assertNotIn(hidden, answer)

    def test_versioned_golden_set_has_required_decision_cases(self) -> None:
        source = Path(__file__).parents[1] / "app" / "data" / "versioned-assist-golden-v1.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        self.assertEqual(payload["caseCount"], len(payload["cases"]))
        self.assertEqual(["증상", "원인", "해결 방법", "추가 고려사항", "적용 버전"], payload["publicDocumentSections"])
        pairs = {(item["expectedCurrentAssessment"], item["expectedPreviewAssessment"]) for item in payload["cases"]}
        self.assertIn(("CURRENT_DEFECT", "PREVIEW_IMPROVED"), pairs)
        self.assertIn(("CURRENT_DEFECT", "PREVIEW_NOT_FOUND"), pairs)
        self.assertIn(("CURRENT_CONFIG_ERROR", "NOT_APPLICABLE"), pairs)
        self.assertIn(("CURRENT_RUNTIME_ISSUE", "NOT_APPLICABLE"), pairs)
        console = next(item for item in payload["cases"] if item["caseKey"] == "MOLD-CONSOLE-CONNECTING-001")
        self.assertEqual("Mold에서 가상머신의 콘솔 보기를 클릭하면 콘솔 화면이 표시되지만 \"연결중\"이라고 표시되고, 더 이상 화면을 보여주지 않습니다. 콘솔을 보려면 어떻게 해야 하나요?", console["question"])
        self.assertIn("query-vnc", console["requiredPublicGuidance"])
        ha_case = next(item for item in payload["cases"] if item["caseKey"] == "COMMUNITY-177-KVM-HA-DEGRADED-001")
        self.assertIn("kvmhapervider", ha_case["question"])
        self.assertIn("mold-agent.service", ha_case["requiredPublicGuidance"])
        self.assertIn("kvmhapervider가 실제 값인지 확인", ha_case["forbiddenPublicClaims"])

    def test_product_first_evidence_priority_is_stable(self) -> None:
        self.assertEqual((1, "ABLESTACK_DOCUMENTATION"), evidence_priority("SHARED_DOCS", "DOCUMENTATION"))
        self.assertEqual((2, "ABLESTACK_SOURCE_CODE"), evidence_priority("CLOUD_DIPLO", "SOURCE_CODE"))
        self.assertEqual(
            (3, "OFFICIAL_PLATFORM_DOCUMENTATION"),
            evidence_priority(CURATED_PLATFORM_PROFILE, "OFFICIAL_EXTERNAL_DOCUMENTATION"),
        )
        self.assertEqual(
            (4, "APPROVED_EXTERNAL_REFERENCE"),
            evidence_priority(CURATED_PLATFORM_PROFILE, "SUPPLEMENTAL_EXTERNAL_REFERENCE"),
        )

    def test_symptom_section_contains_only_user_observed_behavior(self) -> None:
        result = {
            "state": "ANSWERED",
            "report": {
                "summary": "콘솔 창은 열리지만 연결중에서 멈추는 경우 브라우저 연결 문제일 가능성이 있습니다.",
                "observedFacts": [
                    "Mold에서 가상머신 콘솔 창은 표시되지만 연결중 상태에서 더 진행되지 않습니다.",
                    "Mold의 기본 noVNC 뷰어는 Console Proxy VM을 통해 VNC 포트로 연결을 중계합니다.",
                    "현재 릴리스는 WebSocket 연결 요청을 처리하며 세션 검증 실패 시 연결을 끊습니다.",
                    "실제 WebSocket 응답 또는 관련 로그는 제공되지 않았습니다.",
                ],
                "diagnoses": [{"title": "QEMU 프로세스 내부의 VNC 통신 소켓이 이전 연결을 정리하지 못했습니다."}],
                "recommendedActions": ["가상머신 상태를 확인한 뒤 라이브 마이그레이션을 실행합니다."],
                "unknowns": ["여러 가상머신에서 같은 현상이 발생하는지 확인이 필요합니다."],
                "currentAssessment": "CURRENT_RUNTIME_ISSUE",
                "previewAssessment": "NOT_APPLICABLE",
                "previewGuidance": None,
            },
            "citations": [],
        }
        answer = format_knowledge_base(result) or ""
        symptom = answer.split("### 증상", 1)[1].split("### 원인", 1)[0]
        cause = answer.split("### 원인", 1)[1].split("### 해결 방법", 1)[0]
        self.assertIn("콘솔 창은 표시되지만 연결중 상태에서 더 진행되지 않습니다", symptom)
        for forbidden in ("가능성", "noVNC", "Console Proxy", "WebSocket", "로그는 제공", "확인해야"):
            self.assertNotIn(forbidden, symptom)
        self.assertIn("가상머신 실행 프로그램(QEMU)", cause)
        self.assertNotIn("라이브 마이그레이션", cause)

    def test_log_artifact_finding_is_shown_in_cause_without_internal_identifier(self) -> None:
        result = {
            "state": "ANSWERED",
            "report": {
                "summary": "콘솔이 연결중에서 멈춥니다.",
                "observedFacts": ["Mold 가상머신 콘솔이 연결중에서 멈췄습니다."],
                "diagnoses": [{"title": "이전 VNC 연결이 정리되지 않았을 수 있습니다."}],
                "recommendedActions": ["읽기 전용 상태 명령을 확인합니다."],
                "unknowns": [],
                "artifactEvidence": [{
                    "artifactId": "internal-artifact-id",
                    "finding": "첨부 로그에서 이전 VNC 세션이 still_open 상태이고 새 연결은 waiting 상태입니다.",
                    "region": "mold-console.log:2-4",
                }],
                "currentAssessment": "CURRENT_RUNTIME_ISSUE",
                "previewAssessment": "NOT_APPLICABLE",
                "previewGuidance": None,
            },
            "citations": [],
        }
        answer = format_knowledge_base(result) or ""
        cause = answer.split("### 원인", 1)[1].split("### 해결 방법", 1)[0]
        self.assertIn("still_open", cause)
        self.assertIn("waiting", cause)
        self.assertNotIn("internal-artifact-id", answer)
        self.assertNotIn("mold-console.log:2-4", answer)

    def test_noncausal_image_finding_is_shown_only_in_considerations(self) -> None:
        result = {
            "state": "ANSWERED",
            "report": {
                "summary": "콘솔이 연결중에서 멈춥니다.",
                "observedFacts": ["Mold 가상머신 콘솔이 연결중에서 멈췄습니다."],
                "diagnoses": [{"title": "이전 VNC 연결이 정리되지 않았을 수 있습니다."}],
                "recommendedActions": ["읽기 전용 상태 명령을 확인합니다."],
                "unknowns": [],
                "artifactEvidence": [{
                    "artifactId": "image-artifact-id",
                    "finding": "첨부 이미지는 콘솔 화면이 아니라 답변 품질 검증 슬라이드입니다.",
                    "region": "all",
                }],
                "currentAssessment": "CURRENT_RUNTIME_ISSUE",
                "previewAssessment": "NOT_APPLICABLE",
                "previewGuidance": None,
            },
            "citations": [],
        }
        answer = format_knowledge_base(result) or ""
        symptom = answer.split("### 증상", 1)[1].split("### 원인", 1)[0]
        cause = answer.split("### 원인", 1)[1].split("### 해결 방법", 1)[0]
        considerations = answer.split("### 추가 고려사항", 1)[1].split("### 적용 버전", 1)[0]
        self.assertNotIn("품질 검증 슬라이드", symptom)
        self.assertNotIn("품질 검증 슬라이드", cause)
        self.assertIn("품질 검증 슬라이드", considerations)

    def test_abstained_answer_still_asks_for_information_in_a_friendly_voice(self) -> None:
        answer = format_public_answer({"state": "ABSTAINED", "plan": {"questionsNeeded": []}}) or ""
        self.assertIn("확인을 도와드리겠습니다", answer)
        self.assertIn("ABLESTACK Diplo 버전", answer)
        self.assertIn("맥락을 유지", answer)
        self.assertNotIn("###", answer)

        knowledge = format_knowledge_base({"state": "ABSTAINED", "plan": {"questionsNeeded": []}}) or ""
        self.assertIn("### 증상", knowledge)
        self.assertIn("### 원인", knowledge)
        self.assertIn("현재 정보만으로는 원인을 확정할 수 없습니다", knowledge)
        self.assertIn("### 적용 버전", knowledge)


if __name__ == "__main__":
    unittest.main()
