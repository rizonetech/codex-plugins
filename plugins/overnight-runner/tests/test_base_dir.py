import importlib.util
import os
import unittest
from pathlib import Path


def load_module():
    path = Path(__file__).parent.parent / ".codex" / "scripts" / "overnight-runner.py"
    spec = importlib.util.spec_from_file_location("overnight_runner", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BaseDirTests(unittest.TestCase):
    def test_default_base_is_codex(self):
        os.environ.pop("OVERNIGHT_RUNNER_BASE", None)
        mod = load_module()
        self.assertEqual(mod.state_path(Path("/proj")), Path("/proj/.codex/state/overnight-runner.json"))
        self.assertEqual(mod.reports_dir(Path("/proj")), Path("/proj/.codex/reports"))

    def test_env_overrides_base(self):
        os.environ["OVERNIGHT_RUNNER_BASE"] = ".claude/overnight"
        try:
            mod = load_module()
            self.assertEqual(mod.state_path(Path("/proj")), Path("/proj/.claude/overnight/state/overnight-runner.json"))
            self.assertEqual(mod.reports_dir(Path("/proj")), Path("/proj/.claude/overnight/reports"))
        finally:
            del os.environ["OVERNIGHT_RUNNER_BASE"]


if __name__ == "__main__":
    unittest.main()
