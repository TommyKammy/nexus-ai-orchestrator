import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
REGRESSION_SCRIPT = REPO_ROOT / "scripts" / "ci" / "regression.sh"


class RegressionEntrypointTests(unittest.TestCase):
    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _run_regression(self, kubectl_script: str) -> subprocess.CompletedProcess[str]:
        bash_path = shutil.which("bash")
        if bash_path is None:
            raise RuntimeError("bash is required to run regression entrypoint tests")

        tmpdir = Path(tempfile.mkdtemp(prefix="regression-entrypoint-"))
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        bindir = tmpdir / "bin"
        bindir.mkdir()

        self._write_executable(
            bindir / "pnpm",
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                exit 0
                """
            ),
        )
        self._write_executable(bindir / "kubectl", kubectl_script)

        env = os.environ.copy()
        env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"

        return subprocess.run(
            [bash_path, str(REGRESSION_SCRIPT)],  # noqa: S603
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_skips_k8s_smoke_when_current_context_is_not_configured(self):
        result = self._run_regression(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                if [[ "${1:-}" == "config" && "${2:-}" == "current-context" ]]; then
                  echo "error: current-context is not set" >&2
                  exit 1
                fi

                echo "unexpected kubectl invocation: $*" >&2
                exit 97
                """
            )
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(
            "Skipping k8s smoke: kubectl current context is not configured.",
            result.stdout,
        )
        self.assertIn("[regression] complete", result.stdout)

    def test_skips_k8s_smoke_when_namespace_is_not_present(self):
        result = self._run_regression(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                if [[ "${1:-}" == "config" && "${2:-}" == "current-context" ]]; then
                  echo "ci-kind"
                  exit 0
                fi

                if [[ "${1:-}" == "cluster-info" ]]; then
                  exit 0
                fi

                if [[ "${1:-}" == "get" && "${2:-}" == "namespace" && "${3:-}" == "executor-system" ]]; then
                  echo 'Error from server (NotFound): namespaces "executor-system" not found' >&2
                  exit 1
                fi

                echo "unexpected kubectl invocation: $*" >&2
                exit 97
                """
            )
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Skipping k8s smoke: namespace 'executor-system' not found.", result.stdout)

    def test_fails_when_namespace_check_errors_against_available_cluster(self):
        result = self._run_regression(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                if [[ "${1:-}" == "config" && "${2:-}" == "current-context" ]]; then
                  echo "ci-kind"
                  exit 0
                fi

                if [[ "${1:-}" == "cluster-info" ]]; then
                  exit 0
                fi

                if [[ "${1:-}" == "get" && "${2:-}" == "namespace" && "${3:-}" == "executor-system" ]]; then
                  echo 'Error from server (Forbidden): namespaces is forbidden' >&2
                  exit 1
                fi

                echo "unexpected kubectl invocation: $*" >&2
                exit 97
                """
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "k8s smoke gating failed: unable to verify namespace 'executor-system'.",
            result.stderr,
        )
        self.assertIn("Error from server (Forbidden)", result.stderr)


if __name__ == "__main__":
    unittest.main()
