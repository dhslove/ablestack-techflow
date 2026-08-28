"""Bounded official-web fallback for guest operating-system support evidence."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5


REFERENCE_DATA = Path(__file__).with_name("data") / "curated-platform-references-v1.json"

OFFICIAL_WEB_ALLOWED_DOMAINS: tuple[str, ...] = (
    "documentation.ubuntu.com",
    "packages.ubuntu.com",
    "docs.redhat.com",
    "access.redhat.com",
    "docs.rockylinux.org",
    "download.rockylinux.org",
    "docs.fedoraproject.org",
    "docs.debian.org",
    "manpages.debian.org",
    "documentation.suse.com",
    "docs.oracle.com",
    "docs.freebsd.org",
    "man.freebsd.org",
    "wiki.archlinux.org",
    "docs.alpinelinux.org",
    "docs.aws.amazon.com",
    "docs.kali.org",
    "support.apple.com",
    "www.ibm.com",
    "www.qemu.org",
    "qemu.org",
    "libvirt.org",
    "learn.microsoft.com",
    "docs.ceph.com",
    "kubernetes.io",
    "grafana.com",
    "docs.cloudstack.apache.org",
    "cloudstack.apache.org",
)

_GUEST_AGENT_TERMS = (
    "qemu guest agent", "qemu-guest-agent", "qemu-ga", "게스트 에이전트", "에이전트",
)
_INSTALL_TERMS = (
    "설치", "install", "could not be found", "not found", "unit qemu-guest-agent.service",
    "서비스", "service",
)
_GUEST_OS_ACTION_TERMS = (
    "방법", "설정", "구성", "확인", "점검", "동기화", "강제", "명령", "powershell", "쉘", "cli",
    "오류", "실패", "안맞", "맞지", "느림", "접속", "연결", "설치", "서비스", "how", "configure",
    "check", "verify", "troubleshoot", "sync",
)
_TIME_SYNC_TERMS = (
    "ntp", "시간", "시각", "time sync", "time synchronization", "w32time", "w32tm", "동기화",
    "clock", "timezone", "time zone", "표준 시간대",
)
_SMB_MOUNT_TERMS = ("smb", "cifs", "mount.cifs", "smb3", "공유 폴더", "파일 공유")
_OS_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("UBUNTU", ("ubuntu", "우분투")),
    ("RHEL_FAMILY", ("rhel", "red hat", "redhat", "rocky", "almalinux", "centos")),
    ("DEBIAN", ("debian", "데비안")),
    ("SUSE", ("suse", "opensuse", "수세")),
    ("FEDORA", ("fedora", "페도라")),
    ("ORACLE_LINUX", ("oracle linux", "오라클 리눅스")),
    ("FREEBSD", ("freebsd", "프리비에스디")),
    ("ALPINE", ("alpine linux", "알파인 리눅스")),
    ("ARCH", ("arch linux", "아치 리눅스")),
    ("AMAZON_LINUX", ("amazon linux", "아마존 리눅스")),
    ("KALI", ("kali linux", "칼리 리눅스")),
    ("SOLARIS", ("solaris", "솔라리스")),
    ("AIX", ("aix",)),
    ("MACOS", ("macos", "mac os", "맥os", "맥 os")),
    ("WINDOWS", ("windows", "윈도우", "win10", "win11")),
)

_PRODUCT_PLATFORM_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("GLUE", ("glue", "ceph")),
    ("KORAL", ("koral", "kubernetes", "k8s", "kubectl")),
    ("WALL", ("wall", "grafana")),
    ("MOLD", ("mold", "cloudstack")),
)


def guest_os_family(question: str) -> str | None:
    normalized = question.casefold()
    family = next((family for family, terms in _OS_FAMILIES if any(term in normalized for term in terms)), None)
    if family:
        return family
    if "linux" in normalized or "리눅스" in normalized:
        return "GENERIC_LINUX"
    if any(term in normalized for term in ("guest os", "guest operating system", "게스트 운영체제", "가상머신 운영체제")):
        return "GENERIC_GUEST_OS"
    return None


def support_family(question: str) -> str | None:
    guest_family = guest_os_family(question)
    if guest_family:
        return guest_family
    normalized = question.casefold()
    return next(
        (family for family, terms in _PRODUCT_PLATFORM_FAMILIES if any(term in normalized for term in terms)),
        None,
    )


def support_topic(question: str) -> str | None:
    normalized = question.casefold()
    if any(term in normalized for term in _GUEST_AGENT_TERMS):
        return "GUEST_AGENT"
    if any(term in normalized for term in _SMB_MOUNT_TERMS) and any(
        term in normalized for term in ("mount", "마운트", "연결", "fstab")
    ):
        return "SMB_MOUNT"
    if any(term in normalized for term in _TIME_SYNC_TERMS):
        return "TIME_SYNC"
    if guest_os_family(question) and any(term in normalized for term in _GUEST_OS_ACTION_TERMS):
        return "GENERAL_OS"
    return None


def is_guest_os_support_question(question: str) -> bool:
    normalized = question.casefold()
    guest_agent_install = any(term in normalized for term in _GUEST_AGENT_TERMS) and any(
        term in normalized for term in _INSTALL_TERMS
    )
    return bool(guest_os_family(question) and (guest_agent_install or support_topic(question)))


def is_official_platform_support_question(question: str) -> bool:
    return is_guest_os_support_question(question) or support_family(question) in {"GLUE", "KORAL", "WALL", "MOLD"}


def official_web_query(question: str) -> str:
    """Add upstream terminology only to the private search query, never to the user's wording."""
    sanitized = re.sub(r"https?://\S+", "<url>", question, flags=re.IGNORECASE)
    sanitized = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "<email>", sanitized)
    sanitized = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", sanitized)
    sanitized = re.sub(
        r"(?i)\b(password|passwd|secret|token|api[_ -]?key)\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}=<redacted>",
        sanitized,
    )
    family = support_family(question)
    upstream_context = {
        "UBUNTU": "Search only official Ubuntu documentation for this guest operating-system procedure.",
        "RHEL_FAMILY": (
            "Search official Red Hat or Rocky Linux documentation for this guest operating-system procedure."
        ),
        "DEBIAN": "Search only official Debian documentation and Debian manpages for this guest procedure.",
        "SUSE": "Search only official SUSE or openSUSE documentation for this guest procedure.",
        "FEDORA": "Search only official Fedora documentation for this guest procedure.",
        "ORACLE_LINUX": "Search only official Oracle Linux documentation for this guest procedure.",
        "FREEBSD": "Search only official FreeBSD documentation and manpages for this guest procedure.",
        "ALPINE": "Search only official Alpine Linux documentation for this guest procedure.",
        "ARCH": "Search only the official Arch Linux Wiki for this guest procedure.",
        "AMAZON_LINUX": "Search only official AWS Amazon Linux documentation for this guest procedure.",
        "KALI": "Search only official Kali Linux documentation for this guest procedure.",
        "SOLARIS": "Search only official Oracle Solaris documentation for this guest procedure.",
        "AIX": "Search only official IBM AIX documentation for this guest procedure.",
        "MACOS": "Search only official Apple support documentation for this guest procedure.",
        "GENERIC_LINUX": (
            "Identify the Linux distribution named in the question and search only the matching official Linux "
            "vendor documentation from the allowed domain catalog."
        ),
        "GENERIC_GUEST_OS": (
            "Use only official operating-system vendor documentation. If the exact guest OS and version cannot be "
            "identified from the question, return no facts rather than guessing."
        ),
        "WINDOWS": (
            "This is a Windows guest operating-system administration question. Search Microsoft Learn first. "
            "For Windows Server time synchronization, use official W32Time and w32tm guidance and distinguish "
            "domain hierarchy from a manually configured NTP peer."
        ),
        "GLUE": "ABLESTACK Glue uses Ceph. Search the official Ceph documentation for this question.",
        "KORAL": "ABLESTACK Koral uses Kubernetes. Search the official Kubernetes documentation for this question.",
        "WALL": "ABLESTACK Wall uses Grafana. Search only official Grafana documentation for this question.",
        "MOLD": (
            "ABLESTACK Mold is based on Apache CloudStack and manages virtualization through libvirt/QEMU/KVM. "
            "Search official Apache CloudStack documentation first, and use official libvirt or QEMU documentation "
            "when the question concerns a VM runtime, hypervisor, console, migration, storage attachment, or guest agent."
        ),
    }.get(family)
    topic_context = {
        "SMB_MOUNT": (
            "The task is mounting an SMB/CIFS share. Find the official package or mount.cifs documentation and "
            "return exact installation, temporary mount, credential-file, persistent fstab, and verification steps."
        ),
    }.get(support_topic(question))
    context = "\n".join(item for item in (upstream_context, topic_context) if item)
    return f"{context}\n\nUser question:\n{sanitized}" if context else sanitized


def allowed_domains_for_question(question: str) -> tuple[str, ...]:
    """Return the smallest official-domain set for the detected support family."""
    family = support_family(question)
    topic = support_topic(question)
    if family == "WINDOWS" and topic != "GUEST_AGENT":
        return ("learn.microsoft.com",)
    if family == "UBUNTU" and topic != "GUEST_AGENT":
        return ("documentation.ubuntu.com", "packages.ubuntu.com")
    if family == "RHEL_FAMILY" and topic != "GUEST_AGENT":
        return ("docs.redhat.com", "access.redhat.com", "docs.rockylinux.org")
    if family == "DEBIAN":
        return ("docs.debian.org", "manpages.debian.org")
    if family == "SUSE":
        return ("documentation.suse.com",)
    if family == "FEDORA":
        return ("docs.fedoraproject.org",)
    if family == "ORACLE_LINUX":
        return ("docs.oracle.com",)
    if family == "FREEBSD":
        return ("docs.freebsd.org", "man.freebsd.org")
    if family == "ALPINE":
        return ("docs.alpinelinux.org",)
    if family == "ARCH":
        return ("wiki.archlinux.org",)
    if family == "AMAZON_LINUX":
        return ("docs.aws.amazon.com",)
    if family == "KALI":
        return ("docs.kali.org",)
    if family == "SOLARIS":
        return ("docs.oracle.com",)
    if family == "AIX":
        return ("www.ibm.com",)
    if family == "MACOS":
        return ("support.apple.com",)
    if family in {"GENERIC_LINUX", "GENERIC_GUEST_OS"}:
        return OFFICIAL_WEB_ALLOWED_DOMAINS
    domains = {
        "UBUNTU": ("documentation.ubuntu.com", "packages.ubuntu.com", "www.qemu.org", "qemu.org", "libvirt.org"),
        "RHEL_FAMILY": ("docs.redhat.com", "access.redhat.com", "docs.rockylinux.org", "download.rockylinux.org", "www.qemu.org", "qemu.org", "libvirt.org"),
        "WINDOWS": ("docs.redhat.com", "access.redhat.com", "learn.microsoft.com", "www.qemu.org", "qemu.org", "libvirt.org"),
        "GLUE": ("docs.ceph.com",),
        "KORAL": ("kubernetes.io",),
        "WALL": ("grafana.com",),
        "MOLD": ("docs.cloudstack.apache.org", "cloudstack.apache.org", "libvirt.org", "www.qemu.org", "qemu.org"),
    }
    return domains.get(family, OFFICIAL_WEB_ALLOWED_DOMAINS)


def curated_reference_is_stale(*, today: date | None = None) -> bool:
    payload = json.loads(REFERENCE_DATA.read_text(encoding="utf-8"))
    reviewed = date.fromisoformat(str(payload["reviewedAt"]))
    interval = int((payload.get("refreshPolicy") or {}).get("checkIntervalDays") or 30)
    return ((today or datetime.now(timezone.utc).date()) - reviewed).days >= interval


def official_web_search_required(
    question: str,
    local_results: Iterable[dict[str, Any]],
    *,
    stale: bool | None = None,
) -> bool:
    """Search only when a guest-OS procedure lacks an exact fresh official snapshot."""
    if not is_official_platform_support_question(question):
        return False
    reference_is_stale = stale if stale is not None else curated_reference_is_stale()
    if reference_is_stale:
        return True
    family = support_family(question)
    if family is None:
        return True
    family_markers = {
        "UBUNTU": ("ubuntu",),
        "RHEL_FAMILY": ("rhel", "red hat", "rocky"),
        "DEBIAN": ("debian",),
        "SUSE": ("suse", "opensuse"),
        "FEDORA": ("fedora",),
        "ORACLE_LINUX": ("oracle linux",),
        "FREEBSD": ("freebsd",),
        "ALPINE": ("alpine",),
        "ARCH": ("arch linux",),
        "AMAZON_LINUX": ("amazon linux",),
        "KALI": ("kali",),
        "SOLARIS": ("solaris",),
        "AIX": ("aix",),
        "MACOS": ("macos", "mac os"),
        "GENERIC_LINUX": ("linux",),
        "GENERIC_GUEST_OS": ("guest os", "operating system", "운영체제"),
        "WINDOWS": ("windows",),
        "GLUE": ("ceph",),
        "KORAL": ("kubernetes",),
        "WALL": ("grafana",),
        "MOLD": ("cloudstack",),
    }[family]
    topic = support_topic(question)
    topic_markers = {
        "GUEST_AGENT": ("guest agent", "qemu-ga", "qemu guest agent", "게스트 에이전트"),
        "TIME_SYNC": ("ntp", "w32time", "w32tm", "time", "시간", "동기화"),
        "SMB_MOUNT": ("smb", "cifs", "mount.cifs", "smb3", "fstab"),
    }.get(topic)
    if topic_markers is None:
        return True
    return not any(
        str(item.get("sourceKind")) == "OFFICIAL_EXTERNAL_DOCUMENTATION"
        and any(marker in str(item.get("symbol") or "").casefold() for marker in family_markers)
        and any(
            marker in f"{item.get('symbol') or ''}\n{item.get('content') or ''}".casefold()
            for marker in topic_markers
        )
        for item in local_results
    )


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path.rstrip("/"), parsed.query, ""))


def _allowed_url(value: str, allowed_domains: Iterable[str]) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def official_web_results(
    facts: Iterable[dict[str, Any]],
    source_urls: Iterable[str],
    *,
    fetched_at: datetime | None = None,
    allowed_domains: Iterable[str] = OFFICIAL_WEB_ALLOWED_DOMAINS,
) -> list[dict[str, Any]]:
    """Validate tool sources and convert official facts into normal grounded chunks."""
    fetched = (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    allowed = tuple(allowed_domains)
    verified_sources = {_canonical_url(url) for url in source_urls if _allowed_url(str(url), allowed)}
    results: list[dict[str, Any]] = []
    for index, fact in enumerate(facts):
        statement = str(fact.get("statement") or "").strip()
        title = str(fact.get("title") or "공식 운영체제 문서").strip()[:200]
        url = str(fact.get("url") or "").strip()
        if not statement or len(statement) > 2000 or not _allowed_url(url, allowed):
            continue
        if _canonical_url(url) not in verified_sources:
            continue
        digest = hashlib.sha256(f"{url}\n{statement}".encode("utf-8")).hexdigest()
        results.append({
            "chunkId": str(uuid5(NAMESPACE_URL, f"techflow-official-web:{digest}")),
            "sourceVersionId": str(uuid5(NAMESPACE_URL, f"techflow-official-web-version:{digest}")),
            "sourceProfileId": "CURATED_PLATFORM_REFERENCE",
            "repository": urlsplit(url).hostname or "official-web",
            "branch": f"live-web-{fetched.date().isoformat()}",
            "commit": digest,
            "path": url,
            "startLine": 1,
            "endLine": 1,
            "symbol": title or f"공식 운영체제 문서 {index + 1}",
            "sourceKind": "OFFICIAL_LIVE_WEB_DOCUMENTATION",
            "content": statement,
            "fetchedAt": fetched.isoformat(),
        })
    return results[:6]
