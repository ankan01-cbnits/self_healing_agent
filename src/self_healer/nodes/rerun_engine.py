import os
import sys
import ast
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from rich.console import Console

console = Console()


@dataclass
class RerunResult:
    passed: bool
    test_name: str
    returncode: int
    heal_cycles: int = 0


class TestRerunEngine:

    MAX_HEAL_CYCLES = 2

    def __init__(self, project_root: Optional[str] = None):
        self.project_root = Path(project_root or os.getcwd())
        self._runner = self._detect_runner()

    # ── Runner detection ───────────────────────────────────────────────────

    def _detect_runner(self) -> str:
        if os.environ.get("SELF_HEALER_RUNNER"):
            return os.environ["SELF_HEALER_RUNNER"]
        if (self.project_root / "pytest.ini").exists():
            return "pytest"
        if (self.project_root / "pyproject.toml").exists():
            if "[tool.pytest" in (self.project_root / "pyproject.toml").read_text():
                return "pytest"
        if (self.project_root / "playwright.config.ts").exists():
            return "playwright-ts"
        if (self.project_root / "playwright.config.js").exists():
            return "playwright-js"
        if (self.project_root / "jest.config.js").exists():
            return "jest"
        if (self.project_root / "package.json").exists():
            pkg = (self.project_root / "package.json").read_text()
            if '"jest"' in pkg:
                return "jest"
            if '"playwright"' in pkg:
                return "playwright-js"
        return "pytest"

    # ── Public entry point ─────────────────────────────────────────────────

    def rerun_from(
        self,
        test_name: str,
        file_path: Optional[str] = None,
        heal_cycles: int = 0,
    ) -> RerunResult:
        """
        Rerun the fixed test AND every test that follows it in the same file.

        Why re-run all following tests and not just the fixed one:
          pytest collects all tests at startup and holds the selector strings in
          memory. Consecutive tests that reference the same (now-patched) selector
          were already collected with the OLD string, so they would fail identically
          even after the file is fixed on disk.

          Spawning a fresh subprocess forces pytest to re-collect the file from
          scratch, so every test from the failing one onward sees the patched value.
        """
        console.print(
            f"\n[bold cyan][rerun][/bold cyan] Runner: [dim]{self._runner}[/dim]  "
            f"Test: [dim]{test_name}[/dim]"
        )

        resolved_file = file_path or self._file_from_node(test_name)
        cmd = self._build_command(test_name, resolved_file)

        if not cmd:
            console.print("[bold red][rerun][/bold red] Could not build rerun command.")
            return RerunResult(
                passed=False, test_name=test_name,
                returncode=-1, heal_cycles=heal_cycles,
            )

        return self._execute(cmd, test_name, heal_cycles)

    # ── Consecutive-test resolution ────────────────────────────────────────

    def _file_from_node(self, test_name: str) -> Optional[str]:
        """Extract the absolute file path from a pytest node id."""
        if "::" in test_name:
            return str(Path(test_name.split("::")[0]).resolve())
        if test_name.endswith(".py"):
            return str(Path(test_name).resolve())
        return None

    def _collect_tests_from(self, test_name: str, file_path: str) -> list:
        """
        Return all pytest node ids in file_path that come AT OR AFTER test_name,
        in the order they appear in the source file.

        Uses ast.parse so we read file order directly — no pytest subprocess,
        no cache dependency.  Works for top-level functions and methods inside
        test classes.
        """
        func_name = test_name.split("::")[-1] if "::" in test_name else None
        if not func_name or not file_path or not Path(file_path).exists():
            return [test_name]

        try:
            source = Path(file_path).read_text(encoding="utf-8")
            tree   = ast.parse(source)
        except Exception:
            return [test_name]

        # Walk the AST and collect every test function/method in source order.
        # ast.walk visits nodes in breadth-first order which matches line order
        # for a flat file; for classes we sort by lineno to be safe.
        all_funcs = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test"):
                    all_funcs.append((node.lineno, node.name))

        all_funcs.sort(key=lambda x: x[0])   # sort by line number
        ordered_names = [name for _, name in all_funcs]

        try:
            start_idx = ordered_names.index(func_name)
        except ValueError:
            # func not found in AST (e.g. parametrised name mismatch) — run whole file
            return [str(Path(file_path).resolve())]

        rel_file = os.path.relpath(file_path, str(self.project_root))
        node_ids = [
            f"{rel_file}::{name}"
            for name in ordered_names[start_idx:]
        ]

        console.print(
            f"[dim][rerun] {len(node_ids)} test(s) from "
            f"'{func_name}' to end of file[/dim]"
        )
        return node_ids

    # ── Command builders ───────────────────────────────────────────────────

    def _build_command(self, test_name: str, file_path: Optional[str]) -> Optional[list]:
        if self._runner == "pytest":
            return self._pytest_cmd(test_name, file_path)
        if self._runner in ("playwright-ts", "playwright-js"):
            return self._playwright_cmd(test_name, file_path)
        if self._runner == "jest":
            return self._jest_cmd(test_name, file_path)
        return None

    def _pytest_cmd(self, test_name: str, file_path: Optional[str]) -> list:
        """
        Collect the failing test + every test that follows it in the same file,
        then pass them all as explicit node ids to a fresh pytest subprocess.

        Key flags:
          --capture=no      stream stdout/print() live so you see Playwright logs
          -p no:randomly    keep file order — no random shuffling
          --tb=short        readable tracebacks without full stack dumps
        """
        node_ids = self._collect_tests_from(test_name, file_path or "")

        # Resolve every node id to an absolute path so pytest finds the file
        # regardless of the working directory.
        resolved = []
        for nid in node_ids:
            if "::" in nid:
                parts    = nid.split("::")
                abs_file = str(Path(parts[0]).resolve())
                resolved.append("::".join([abs_file] + parts[1:]))
            else:
                resolved.append(str(Path(nid).resolve()))

        return [
            sys.executable, "-m", "pytest",
            *resolved,
            "-v",
            "--no-header",
            "--tb=short",
            "--capture=no",
            "-p", "no:randomly",
        ]

    def _playwright_cmd(self, test_name: str, file_path: Optional[str]) -> list:
        """
        Playwright Test re-collects on every invocation so there is no stale
        in-memory state issue.  Run the whole spec file — Playwright will
        execute all tests inside it in order.
        """
        npx  = "npx.cmd" if sys.platform == "win32" else "npx"
        spec = file_path or (test_name.split("::")[0] if "::" in test_name else test_name)
        return [npx, "playwright", "test", spec, "--reporter=line"]

    def _jest_cmd(self, test_name: str, file_path: Optional[str]) -> list:
        """
        Jest also re-collects fresh per run.  --runInBand keeps tests serial
        so browser sessions don't race each other.
        """
        npx  = "npx.cmd" if sys.platform == "win32" else "npx"
        spec = file_path or test_name.split("::")[0]
        return [npx, "jest", spec, "--verbose", "--no-coverage", "--runInBand"]

    # ── Execution ──────────────────────────────────────────────────────────

    def _execute(self, cmd: list, test_name: str, heal_cycles: int) -> RerunResult:
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]\n")

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                text=True,
                # capture_output intentionally omitted → streams live to terminal
            )
        except FileNotFoundError as e:
            console.print(f"[bold red][rerun][/bold red] Command not found: {e}")
            return RerunResult(
                passed=False, test_name=test_name,
                returncode=-1, heal_cycles=heal_cycles,
            )

        passed = proc.returncode == 0

        if passed:
            console.print(f"\n[bold green]✓ All reruns PASSED[/bold green]  [dim]{test_name}[/dim]")
        else:
            console.print(f"\n[bold red]✗ Rerun FAILED[/bold red]  [dim]{test_name}[/dim]")

        return RerunResult(
            passed=passed, test_name=test_name,
            returncode=proc.returncode, heal_cycles=heal_cycles,
        )