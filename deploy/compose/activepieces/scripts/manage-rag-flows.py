#!/usr/bin/env python3
"""Idempotently publish a validated TechFlow Activepieces flow bundle.

Authentication values are accepted only through process environment variables.
The script never prints tokens, passwords, or authentication responses.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def api(base: str, path: str, method: str = "GET", body: dict[str, Any] | None = None,
        token: str | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from None


def http_action(operation: dict[str, Any], base_url: str, index: int) -> dict[str, Any]:
    body = operation.get("body")
    correlation = "{{trigger['output']['body']['correlationId']}}"
    event_id = "{{trigger['output']['body']['eventId']}}"
    action = {
        "name": operation["name"], "type": "PIECE", "valid": True,
        "displayName": operation["name"].replace("_", " ").title(),
        "lastUpdatedDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "settings": {
            "input": {
                "url": base_url + operation["url"], "method": operation["method"],
                "headers": {"Content-Type": "application/json", "X-Correlation-Id": correlation,
                            "Idempotency-Key": f"{event_id}-{operation['name']}"},
                "timeout": int(operation.get("timeoutSeconds", 120)), "authType": "NONE", "body_type": "json",
                "use_proxy": False, "authFields": {}, "failureMode": "continue_none",
                "queryParams": {}, "followRedirects": False, "response_is_binary": False,
            },
            "pieceName": "@activepieces/piece-http", "actionName": "send_request",
            "pieceVersion": "0.11.14", "propertySettings": {},
        },
    }
    if body is not None and operation["method"] not in {"GET", "HEAD"}:
        action["settings"]["input"]["body"] = {"data": body}
    return action


def build_trigger(flow: dict[str, Any], base_url: str) -> dict[str, Any]:
    trigger: dict[str, Any] = {
        "name": "trigger", "type": "PIECE_TRIGGER", "valid": True,
        "displayName": "Verified TechFlow Webhook",
        "lastUpdatedDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "settings": {
            "input": {"authType": "none", "authFields": {}},
            "pieceName": "@activepieces/piece-webhook", "triggerName": "catch_webhook",
            "pieceVersion": "0.1.39", "propertySettings": {"authFields": {"type": "MANUAL", "schema": {}}},
        },
    }
    previous = None
    for index, operation in reversed(list(enumerate(flow["operations"]))):
        action = http_action(operation, base_url, index)
        action["nextAction"] = previous
        previous = action
    trigger["nextAction"] = previous
    return trigger


def sign_in(base: str) -> tuple[str, str]:
    email = os.environ.get("TECHFLOW_ACTIVEPIECES_EMAIL", "")
    password = os.environ.get("TECHFLOW_ACTIVEPIECES_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("TECHFLOW_ACTIVEPIECES_EMAIL and TECHFLOW_ACTIVEPIECES_PASSWORD are required")
    result = api(base, "/api/v1/authentication/sign-in", "POST", {"email": email, "password": password})
    token = result.get("token") or result.get("accessToken")
    project_id = result.get("projectId") or (result.get("project") or {}).get("id")
    if not token or not project_id:
        raise RuntimeError("Activepieces authentication response did not contain required runtime fields")
    return token, project_id


def publish(base: str, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    token, project_id = sign_in(base)
    current = api(base, f"/api/v1/flows?projectId={project_id}&limit=100", token=token)
    rows: list[dict[str, Any]] = []
    candidates: list[Any] = [current]
    while candidates:
        candidate = candidates.pop()
        if isinstance(candidate, list) and all(isinstance(item, dict) for item in candidate):
            if not candidate or all(
                "id" in item and (
                    "displayName" in item or isinstance(item.get("version"), dict)
                ) for item in candidate
            ):
                rows = candidate
                break
            candidates.extend(candidate)
        elif isinstance(candidate, dict):
            candidates.extend(candidate.values())
    rows.sort(key=lambda row: row.get("updated", ""))
    by_name = {
        row.get("displayName") or (row.get("version") or {}).get("displayName"): row
        for row in rows
        if row.get("displayName") or (row.get("version") or {}).get("displayName")
    }
    results = []
    for flow in bundle["flows"]:
        existing = by_name.get(flow["displayName"])
        if existing:
            flow_id = existing["id"]
        else:
            created = api(base, "/api/v1/flows", "POST", {
                "displayName": flow["displayName"], "projectId": project_id,
                "metadata": {"techflowLogicalId": flow["logicalId"], "issue": bundle["issue"]},
            }, token)
            flow_id = created["id"]
        imported = api(base, f"/api/v1/flows/{flow_id}", "POST", {
            "type": "IMPORT_FLOW", "request": {
                "displayName": flow["displayName"],
                "trigger": build_trigger(flow, bundle["gatewayBaseUrl"]),
                "schemaVersion": str(bundle["schemaVersion"]),
                "notes": [],
            },
        }, token)
        published = api(base, f"/api/v1/flows/{flow_id}", "POST", {
            "type": "LOCK_AND_PUBLISH", "request": {"status": "ENABLED"},
        }, token)
        results.append({"logicalId": flow["logicalId"], "flowId": flow_id,
                        "status": published.get("status", "ENABLED"),
                        "publishedVersionId": published.get("publishedVersionId") or imported.get("version", {}).get("id")})
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://172.16.0.231:8080")
    parser.add_argument("--bundle", type=Path, default=Path(__file__).parents[1] / "flows" / "rag-orchestration-v1.json")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    flow_count = len(bundle.get("flows", []))
    if not 1 <= flow_count <= 10 or bundle.get("security", {}).get("automaticApproval") is not False:
        raise RuntimeError("invalid TechFlow flow bundle")
    if args.validate_only:
        print(json.dumps({"valid": True, "flowCount": flow_count}, ensure_ascii=False))
        return 0
    print(json.dumps(publish(args.base_url, bundle), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"flow deployment failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
