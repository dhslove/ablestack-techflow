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
_OS_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("UBUNTU", ("ubuntu", "우분투")),
    ("RHEL_FAMILY", ("rhel", "red hat", "redhat", "rocky", "almalinux", "centos")),
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
    return next((family for family, terms in _OS_FAMILIES if any(term in normalized for term in terms)), None)


def support_family(question: str) -> str | None:
    guest_family = guest_os_family(question)
    if guest_family:
        return guest_family
    normalized = question.casefold()
    return next(
        (family for family, terms in _PRODUCT_PLATFORM_FAMILIES if any(term in normalized for term in terms)),
        None,
    )


def is_guest_os_support_question(question: str) -> bool:
    normalized = question.casefold()
    return any(term in normalized for term in _GUEST_AGENT_TERMS) and any(
        term in normalized for term in _INSTALL_TERMS
    )


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
        "GLUE": "ABLESTACK Glue uses Ceph. Search the official Ceph documentation for this question.",
        "KORAL": "ABLESTACK Koral uses Kubernetes. Search the official Kubernetes documentation for this question.",
        "WALL": "ABLESTACK Wall uses Grafana. Search only official Grafana documentation for this question.",
        "MOLD": (
            "ABLESTACK Mold is based on Apache CloudStack and manages virtualization through libvirt/QEMU/KVM. "
            "Search official Apache CloudStack documentation first, and use official libvirt or QEMU documentation "
            "when the question concerns a VM runtime, hypervisor, console, migration, storage attachment, or guest agent."
        ),
    }.get(family)
    return f"{upstream_context}\n\nUser question:\n{sanitized}" if upstream_context else sanitized


def allowed_domains_for_question(question: str) -> tuple[str, ...]:
    """Return the smallest official-domain set for the detected support family."""
    domains = {
        "UBUNTU": ("documentation.ubuntu.com", "packages.ubuntu.com", "www.qemu.org", "qemu.org", "libvirt.org"),
        "RHEL_FAMILY": ("docs.redhat.com", "access.redhat.com", "docs.rockylinux.org", "download.rockylinux.org", "www.qemu.org", "qemu.org", "libvirt.org"),
        "WINDOWS": ("docs.redhat.com", "access.redhat.com", "learn.microsoft.com", "www.qemu.org", "qemu.org", "libvirt.org"),
        "GLUE": ("docs.ceph.com",),
        "KORAL": ("kubernetes.io",),
        "WALL": ("grafana.com",),
        "MOLD": ("docs.cloudstack.apache.org", "cloudstack.apache.org", "libvirt.org", "www.qemu.org", "qemu.org"),
    }
    return domains.get(support_family(question), OFFICIAL_WEB_ALLOWED_DOMAINS)


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
        "WINDOWS": ("windows",),
        "GLUE": ("ceph",),
        "KORAL": ("kubernetes",),
        "WALL": ("grafana",),
        "MOLD": ("cloudstack",),
    }[family]
    return not any(
        str(item.get("sourceKind")) == "OFFICIAL_EXTERNAL_DOCUMENTATION"
        and any(marker in str(item.get("symbol") or "").casefold() for marker in family_markers)
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
