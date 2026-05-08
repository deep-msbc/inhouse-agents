"""
CLIInvoker — async subprocess wrapper for djcli.

Responsibilities:
  - Resolve output_path via the 3-step fallback chain (caller → env → default)
  - Build the djcli command with locked flags (--api always, --auth never)
  - Execute djcli via asyncio.to_thread(subprocess.run, ...) — NEVER blocking
  - Return CLIInvokerResult with stdout/stderr captured for DB persistence

CLIInvokerResult is defined here (NOT in backend_pipeline.py) — it is an
internal transport type, not a public schema contract.

Fallback chain for output_path (evaluated in invoke()):
  1. input.output_path          — caller wins (always set in CLIInvokerInput)
  2. DJCLI_OUTPUT_DIR env var   — operator-level default
  3. ./generated_projects/{project_name}  — last resort
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from typing import NamedTuple

from src.msbc.models.schemas.backend_pipeline import CLIInvokerInput, CLIInvokerOutput

logger = logging.getLogger(__name__)

# ── Timeout for the djcli subprocess (seconds) ────────────────────────────────
_DJCLI_TIMEOUT: int = 60


# ── Result transport type (internal — not a public schema) ────────────────────

class CLIInvokerResult(NamedTuple):
    """
    Internal result returned by CLIInvoker.invoke().

    output  — structured CLIInvokerOutput (success flag, paths, errors)
    stdout  — raw subprocess stdout (persisted to backend_generations.cli_stdout)
    stderr  — raw subprocess stderr (persisted to backend_generations.cli_stderr)
    """
    output: CLIInvokerOutput
    stdout: str
    stderr: str


# ── Invoker ───────────────────────────────────────────────────────────────────

class CLIInvoker:
    """
    Wraps the djcli subprocess call.

    Usage::

        invoker = CLIInvoker()
        result = await invoker.invoke(cli_input)
        if result.output.success:
            ...
    """

    async def invoke(self, input: CLIInvokerInput) -> CLIInvokerResult:
        """
        Invoke djcli and return the structured result.

        Dispatches to the correct djcli subcommand based on input.generation_mode.
        startapp fires one subprocess per app; all others fire one subprocess total.

        Parameters
        ----------
        input : CLIInvokerInput
            Typed input with project_name, app_names, output_path, generation_mode, etc.

        Returns
        -------
        CLIInvokerResult
            Named tuple of (CLIInvokerOutput, stdout_str, stderr_str).
        """
        output_path = self._resolve_output_path(input)
        os.makedirs(output_path, exist_ok=True)

        commands = self._build_commands(input, output_path)

        mode = (
            input.generation_mode.value
            if hasattr(input.generation_mode, "value")
            else str(input.generation_mode)
        )

        if not commands:
            # noop — return success with a sensible project_path
            project_path = os.path.join(output_path, input.project_name)
            return CLIInvokerResult(
                output=CLIInvokerOutput(
                    success=True,
                    errors=[],
                    project_path=project_path,
                    framework=input.framework,
                    generated_apps=list(input.app_names),
                    skipped_apps=[],
                ),
                stdout="",
                stderr="",
            )

        logger.info(
            "CLIInvoker: mode=%r project=%r apps=%r output_path=%r commands=%d",
            mode,
            input.project_name,
            input.app_names,
            output_path,
            len(commands),
        )

        all_stdout: list[str] = []
        all_stderr: list[str] = []

        for cmd in commands:
            logger.debug("CLIInvoker: running %r", cmd)
            try:
                proc: subprocess.CompletedProcess = await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=_DJCLI_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                msg = f"djcli timed out after {_DJCLI_TIMEOUT}s"
                logger.error("CLIInvoker: %s", msg)
                return CLIInvokerResult(
                    output=CLIInvokerOutput(
                        success=False,
                        errors=[msg],
                        project_path=output_path,
                        framework=input.framework,
                        generated_apps=[],
                        skipped_apps=[],
                    ),
                    stdout="\n".join(all_stdout),
                    stderr="\n".join(all_stderr),
                )

            all_stdout.append(proc.stdout or "")
            all_stderr.append(proc.stderr or "")

            if proc.returncode != 0:
                error_detail = (proc.stderr or "").strip() or f"djcli exited with code {proc.returncode}"
                logger.error("CLIInvoker: djcli failed (rc=%d) — %s", proc.returncode, error_detail)
                return CLIInvokerResult(
                    output=CLIInvokerOutput(
                        success=False,
                        errors=[error_detail],
                        project_path=output_path,
                        framework=input.framework,
                        generated_apps=[],
                        skipped_apps=[],
                    ),
                    stdout="\n".join(all_stdout),
                    stderr="\n".join(all_stderr),
                )

        # All commands succeeded — compute project_path per mode
        existing_name = (input.existing_project_name or "").strip()
        if mode == "startproject":
            project_path = os.path.join(output_path, input.project_name)
        elif mode == "startapp":
            project_path = os.path.join(output_path, existing_name or input.project_name)
        else:  # startservices
            project_path = output_path

        logger.info(
            "CLIInvoker: all djcli commands succeeded — project_path=%r apps=%r",
            project_path,
            input.app_names,
        )
        return CLIInvokerResult(
            output=CLIInvokerOutput(
                success=True,
                errors=[],
                project_path=project_path,
                framework=input.framework,
                generated_apps=list(input.app_names),
                skipped_apps=[],
            ),
            stdout="\n".join(all_stdout),
            stderr="\n".join(all_stderr),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_output_path(input: CLIInvokerInput) -> str:
        """
        Resolve the output directory using the 3-step fallback chain:
          1. input.output_path          (caller-supplied — always present)
          2. DJCLI_OUTPUT_DIR env var   (operator override)
          3. ./generated_projects/{project_name}  (safe default)
        """
        if input.output_path:
            return input.output_path
        env_dir = os.environ.get("DJCLI_OUTPUT_DIR", "").strip()
        if env_dir:
            return env_dir
        return os.path.join("generated_projects", input.project_name)

    @staticmethod
    def _build_commands(input: CLIInvokerInput, output_path: str) -> list[list[str]]:
        """
        Build the list of djcli commands to run sequentially.

        Returns a list of command lists.  startapp returns one list per app;
        startproject and startservices return a single-element list.
        Returns [] for noop.

        Invariants (locked by architecture):
          --api   is ALWAYS included (startproject only)
          --auth  is NEVER included
        """
        djcli_bin = os.path.join(os.path.dirname(sys.executable), "djcli")
        assert not input.use_auth, "use_auth must be False — --auth is locked off"
        assert input.use_api,     "use_api must be True  — --api  is locked on"

        mode = (
            input.generation_mode.value
            if hasattr(input.generation_mode, "value")
            else str(input.generation_mode)
        )

        if mode == "startproject":
            app_flags: list[str] = []
            for app in input.app_names:
                app_flags += ["--app", app]
            return [[
                djcli_bin, "startproject",
                input.project_name,
                "--api",
                "--path", output_path,
                *app_flags,
            ]]

        elif mode == "startapp":
            # One djcli startapp call per app — existing_project_name resolves the target project dir
            project_target = (input.existing_project_name or "").strip() or input.project_name
            cmds: list[list[str]] = []
            for app in input.app_names:
                cmds.append([
                    djcli_bin, "startapp",
                    "--app", app,
                    "--project", os.path.join(output_path, project_target),
                ])
            return cmds

        elif mode == "startservices":
            # Format: djcli startservices svc_app1:app1 svc_app2:app2 --path output_path
            service_args = [f"svc_{app}:{app}" for app in input.app_names]
            return [[
                djcli_bin, "startservices",
                *service_args,
                "--path", output_path,
            ]]

        else:
            return []  # noop