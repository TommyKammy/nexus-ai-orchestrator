import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ci" / "compose_core_journey.sh"


class ComposeCoreJourneyPatchTests(unittest.TestCase):
    maxDiff = None
    WORKFLOW_PATH = REPO_ROOT / "n8n" / "workflows-v3" / "01_memory_ingest.json"

    def _extract_patch_01(self) -> str:
        script_text = SCRIPT_PATH.read_text(encoding="utf-8")
        match = re.search(
            r"""cat >"\$\{TMP_DIR\}/patch_01\.jq" <<'JQ'\n(.*?)\nJQ""",
            script_text,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "patch_01.jq heredoc not found")
        return match.group(1)

    def test_patch_01_preserves_validate_and_filter_logic_from_checked_in_workflow(self):
        jq_path = shutil.which("jq")
        if jq_path is None:
            self.fail("jq executable not found in PATH")

        with tempfile.TemporaryDirectory(prefix="compose-core-journey-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            patch_path = tmpdir_path / "patch_01.jq"

            patch_path.write_text(self._extract_patch_01(), encoding="utf-8")
            original_workflow = json.loads(
                self.WORKFLOW_PATH.read_text(encoding="utf-8")
            )
            original_js_code = next(
                node["parameters"]["jsCode"]
                for node in original_workflow["nodes"]
                if node["name"] == "Validate and Filter"
            )

            result = subprocess.run(
                [
                    jq_path,
                    "--arg",
                    "name",
                    "ci-name",
                    "--arg",
                    "path",
                    "ci/path",
                    "-f",
                    str(patch_path),
                    str(self.WORKFLOW_PATH),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            patched = json.loads(result.stdout)
            js_code = next(
                node["parameters"]["jsCode"]
                for node in patched["nodes"]
                if node["name"] == "Validate and Filter"
            )

            self.assertEqual(js_code, original_js_code)
            self.assertEqual(patched["name"], "ci-name")
            self.assertEqual(
                patched["connections"]["Check Validation"]["main"][0][0]["node"],
                "Validation Error?",
            )
            self.assertEqual(
                patched["connections"]["Check Policy"]["main"][0][0]["node"],
                "Policy Error?",
            )
            self.assertEqual(
                patched["connections"]["Validation Error?"]["main"][1][0]["node"],
                "Evaluate Policy",
            )
            self.assertEqual(
                patched["connections"]["Policy Error?"]["main"][1][0]["node"],
                "Insert Facts",
            )


if __name__ == "__main__":
    unittest.main()
