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

    def _extract_patch_01(self) -> str:
        script_text = SCRIPT_PATH.read_text(encoding="utf-8")
        match = re.search(
            r"""cat >"\$\{TMP_DIR\}/patch_01\.jq" <<'JQ'\n(.*?)\nJQ""",
            script_text,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "patch_01.jq heredoc not found")
        return match.group(1)

    def test_patch_01_preserves_generated_content_hash_for_service_boundary_vector_insert(self):
        jq_path = shutil.which("jq")
        if jq_path is None:
            self.fail("jq executable not found in PATH")

        with tempfile.TemporaryDirectory(prefix="compose-core-journey-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            patch_path = tmpdir_path / "patch_01.jq"
            workflow_path = tmpdir_path / "workflow.json"

            patch_path.write_text(self._extract_patch_01(), encoding="utf-8")
            workflow_path.write_text(
                json.dumps(
                    {
                        "name": "seed",
                        "nodes": [
                            {
                                "name": "Validate and Filter",
                                "parameters": {"jsCode": "return []"},
                            }
                        ],
                        "connections": {},
                    }
                ),
                encoding="utf-8",
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
                    str(workflow_path),
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

            self.assertIn("createHash('sha256')", js_code)
            self.assertIn("content_hash: contentHash", js_code)
            self.assertIn("request_id: requestId", js_code)
            self.assertIn("metadata", js_code)
            self.assertNotIn("content_hash: null", js_code)


if __name__ == "__main__":
    unittest.main()
