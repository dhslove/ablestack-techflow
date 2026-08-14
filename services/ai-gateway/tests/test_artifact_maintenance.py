from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4


SPEC = importlib.util.spec_from_file_location(
    "artifact_maintenance", Path(__file__).parents[1] / "scripts" / "artifact_maintenance.py"
)
artifact_maintenance = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(artifact_maintenance)


class ArtifactMaintenanceTests(unittest.TestCase):
    def test_expired_artifact_is_removed_and_capacity_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_id = uuid4()
            (root / f"{artifact_id}.bin").write_bytes(b"expired")
            (root / f"{artifact_id}.json").write_text(
                json.dumps({
                    "artifactId": str(artifact_id), "filename": "expired.log", "mediaType": "text/plain",
                    "sha256": "ignored", "sizeBytes": 7, "kind": "LOG", "width": None, "height": None,
                    "entryCount": 1, "extractedBytes": 7, "evidenceTruncated": False, "redactionCount": 0,
                    "createdAt": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                    "expiresAt": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                }), encoding="utf-8",
            )
            with patch.dict("os.environ", {
                "TECHFLOW_ARTIFACT_DISK_WARN_PERCENT": "98",
                "TECHFLOW_ARTIFACT_DISK_CRITICAL_PERCENT": "99",
            }, clear=False):
                result = artifact_maintenance.maintain_once(root)
            self.assertEqual(1, result["removed"])
            self.assertIn(result["level"], {"ok", "warning", "critical"})
            self.assertFalse((root / f"{artifact_id}.bin").exists())

    def test_invalid_capacity_thresholds_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "TECHFLOW_ARTIFACT_DISK_WARN_PERCENT": "90",
            "TECHFLOW_ARTIFACT_DISK_CRITICAL_PERCENT": "80",
        }, clear=False):
            with self.assertRaises(RuntimeError):
                artifact_maintenance.maintain_once(Path(directory))


if __name__ == "__main__":
    unittest.main()
