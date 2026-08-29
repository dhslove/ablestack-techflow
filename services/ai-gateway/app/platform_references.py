"""Locally pinned, reviewer-approved virtualization reference evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5


REFERENCE_DATA = Path(__file__).with_name("data") / "curated-platform-references-v1.json"


def _load_reference_set() -> dict[str, Any]:
    payload = json.loads(REFERENCE_DATA.read_text(encoding="utf-8"))
    if payload.get("reviewStatus") != "APPROVED":
        return {"entries": []}
    return payload


def curated_platform_results(question: str) -> list[dict[str, Any]]:
    """Return local evidence only; answering never depends on a live web request."""
    normalized = question.casefold()
    results: list[dict[str, Any]] = []
    for entry in _load_reference_set().get("entries", []):
        terms = [str(item).casefold() for item in entry.get("matchTerms", ())]
        if not any(term in normalized for term in terms):
            continue
        required_groups = [
            [str(term).casefold() for term in group]
            for group in entry.get("requiredTermGroups", ())
        ]
        if required_groups and not all(any(term in normalized for term in group) for group in required_groups):
            continue
        locator = str(entry["sourceLocator"])
        content = str(entry["content"])
        digest = hashlib.sha256(f"{locator}\n{content}".encode("utf-8")).hexdigest()
        entry_id = str(entry["entryId"])
        results.append({
            "chunkId": str(uuid5(NAMESPACE_URL, f"techflow-platform-reference:{entry_id}:{digest}")),
            "sourceVersionId": str(uuid5(NAMESPACE_URL, f"techflow-platform-reference-version:{digest}")),
            "sourceProfileId": "CURATED_PLATFORM_REFERENCE",
            "repository": str(entry["authority"]),
            "branch": "approved-v1",
            "commit": digest,
            "path": locator,
            "startLine": 1,
            "endLine": max(1, content.count("\n") + 1),
            "symbol": str(entry["title"]),
            "sourceKind": str(entry["authority"]),
            "content": content,
        })
    return results
