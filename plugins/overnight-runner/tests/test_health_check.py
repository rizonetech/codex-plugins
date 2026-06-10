"""Unit tests for overnight-runner health-check failure paths and helpers.

Run with:
    python3 -m unittest discover plugins/overnight-runner/tests
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Load the script as a module via importlib (it has no __init__.py package).
# ---------------------------------------------------------------------------
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "overnight-runner.py"

spec = importlib.util.spec_from_file_location("overnight_runner", _SCRIPT)
assert spec is not None and spec.loader is not None, f"Cannot load {_SCRIPT}"
_mod: types.ModuleType = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)  # type: ignore[union-attr]

chromemcp_health = _mod.chromemcp_health
find_chromemcp_roots = _mod.find_chromemcp_roots
normalize_gate_name = _mod.normalize_gate_name
CHROMEMCP_HEALTH_URL = _mod.CHROMEMCP_HEALTH_URL


# ---------------------------------------------------------------------------
# Helper: build a minimal fake HTTP response context-manager.
# ---------------------------------------------------------------------------
def _make_response(status: int, body: bytes) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    return response


class TestChromeMcpHealthBlocked(unittest.TestCase):
    """chromemcp_health returns 'blocked' + recovery hint when urlopen raises URLError."""

    def test_url_error_yields_blocked(self) -> None:
        root = Path(tempfile.mkdtemp())
        with patch.object(urllib.request, "urlopen", side_effect=urllib.error.URLError("connection refused")):
            result = chromemcp_health(root)

        self.assertEqual(result["status"], "blocked")
        self.assertIn("error", result)
        self.assertIn("recovery", result)
        self.assertEqual(result["url"], CHROMEMCP_HEALTH_URL)


class TestChromeMcpHealthFailed(unittest.TestCase):
    """chromemcp_health returns 'failed' on a non-200 response (status 500)."""

    def test_non_200_yields_failed(self) -> None:
        root = Path(tempfile.mkdtemp())
        fake_response = _make_response(500, b"{}")
        with patch.object(urllib.request, "urlopen", return_value=fake_response):
            result = chromemcp_health(root)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["http_status"], 500)
        self.assertEqual(result["url"], CHROMEMCP_HEALTH_URL)


class TestChromeMcpHealthPassed(unittest.TestCase):
    """chromemcp_health returns 'passed' and passes through visible_interactions."""

    def test_200_with_valid_json_yields_passed(self) -> None:
        root = Path(tempfile.mkdtemp())
        payload = b'{"visibleInteractions": 3}'
        fake_response = _make_response(200, payload)
        with patch.object(urllib.request, "urlopen", return_value=fake_response):
            result = chromemcp_health(root)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["visible_interactions"], 3)


class TestFindChromeMcpRootsEnvHome(unittest.TestCase):
    """find_chromemcp_roots honours CHROMEMCP_HOME env var."""

    def test_env_home_is_first_element(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {**os.environ, "CHROMEMCP_HOME": tmpdir}
            with patch.dict(os.environ, env, clear=True):
                roots = find_chromemcp_roots(Path(tmpdir))

        self.assertTrue(len(roots) >= 1, "Expected at least one root")
        self.assertEqual(roots[0], tmpdir)


class TestNormalizeGateName(unittest.TestCase):
    """normalize_gate_name maps chromemcp_local -> browser_verification."""

    def test_legacy_name_mapped(self) -> None:
        self.assertEqual(normalize_gate_name("chromemcp_local"), "browser_verification")

    def test_canonical_name_unchanged(self) -> None:
        self.assertEqual(normalize_gate_name("browser_verification"), "browser_verification")

    def test_unrelated_name_unchanged(self) -> None:
        self.assertEqual(normalize_gate_name("implemented"), "implemented")
        self.assertEqual(normalize_gate_name("visual_qa"), "visual_qa")
        self.assertEqual(normalize_gate_name("rollback_plan"), "rollback_plan")


if __name__ == "__main__":
    unittest.main()
