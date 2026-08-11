from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class HermesCLIError(RuntimeError):
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    def __str__(self) -> str:
        detail = (self.stderr or self.stdout or "Hermes command failed").strip()
        return f"{detail} (exit {self.returncode})"


class HermesCLI:
    def __init__(self, hermes: str | None = None) -> None:
        self.hermes = hermes or shutil.which("hermes") or "hermes"

    def profile_command(self, profile: str | None, *args: str) -> list[str]:
        name = str(profile or "default").strip().lower()
        return [self.hermes, *(() if name == "default" else ("-p", name)), *args]

    @staticmethod
    def profile_env(home: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["HERMES_HOME"] = str(home)
        return env

    def run_text(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> str:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            raise HermesCLIError(command, proc.returncode, proc.stdout, proc.stderr)
        return proc.stdout.strip()

    def run_json(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> Any:
        text = self.run_text(command, env=env, timeout=timeout)
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Hermes command did not return JSON: {text[:500]}") from exc
