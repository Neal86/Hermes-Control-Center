from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
from compatibility import HermesCLI  # noqa: E402

_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _safe_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required for Hermes management")
    try:
        value = yaml.safe_load(path.read_text("utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def _nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _path_key(value: str | Path | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    try:
        path = path.resolve(strict=False)
    except (OSError, ValueError):
        path = Path(os.path.abspath(os.path.normpath(str(path))))
    return os.path.normcase(os.path.normpath(str(path)))


class ManagementCenter:
    """Management layer over native Hermes Profiles and Projects."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")).expanduser().resolve()
        self.cli = HermesCLI()
        self.hermes = self.cli.hermes

    @staticmethod
    def _normalize_profile(name: str | None) -> str:
        value = str(name or "default").strip().lower()
        if value == "default":
            return value
        if not _PROFILE_RE.fullmatch(value):
            raise ValueError("invalid profile name")
        return value

    def _profile_home(self, name: str | None) -> Path:
        profile = self._normalize_profile(name)
        if profile == "default":
            return self.root
        profiles_root = (self.root / "profiles").resolve()
        home = (profiles_root / profile).resolve()
        if profiles_root not in home.parents:
            raise ValueError("invalid profile path")
        if not home.is_dir():
            raise ValueError(f"unknown Hermes profile: {profile}")
        return home

    def _profile_cli(self, name: str | None, *args: str) -> list[str]:
        return self.cli.profile_command(self._normalize_profile(name), *args)

    def _env_for(self, name: str | None) -> dict[str, str]:
        # Profile selection is already carried by ``-p <name>`` in
        # ``_profile_cli``. Pointing HERMES_HOME at the profile directory as
        # well makes Hermes resolve the profile twice (profiles/<name>/profiles/<name>)
        # and can leave gateway state files referring to another profile.
        self._profile_home(name)  # Validate the requested profile first.
        return self.cli.profile_env(self.root)

    def _active_profile(self) -> str:
        marker = self.root / "active_profile"
        try:
            value = marker.read_text("utf-8").strip().lower()
            if value and (value == "default" or _PROFILE_RE.fullmatch(value)):
                return value
        except OSError:
            pass
        return "default"

    def profile_names(self) -> list[str]:
        names = ["default"]
        root = self.root / "profiles"
        if root.is_dir():
            for item in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                name = item.name.lower()
                if item.is_dir() and _PROFILE_RE.fullmatch(name):
                    names.append(name)
        return names

    @staticmethod
    def _parse_profile_show(text: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for raw in text.splitlines():
            if ":" not in raw:
                continue
            key, value = raw.split(":", 1)
            key = key.strip().lower().replace(" ", "_")
            if key:
                result[key] = value.strip()
        return result

    def _agent_file_snapshot(self, profile: str) -> dict[str, Any]:
        home = self._profile_home(profile)
        config = _safe_yaml(home / "config.yaml")
        metadata = _safe_yaml(home / "profile.yaml")
        soul_path = home / "SOUL.md"
        try:
            soul = soul_path.read_text("utf-8") if soul_path.exists() else ""
        except OSError:
            soul = ""
        skills_count = 0
        skills_dir = home / "skills"
        if skills_dir.is_dir():
            try:
                skills_count = sum(1 for p in skills_dir.iterdir() if p.is_dir())
            except OSError:
                pass
        cron_count = 0
        cron_path = home / "cron" / "jobs.json"
        try:
            payload = json.loads(cron_path.read_text("utf-8")) if cron_path.exists() else {}
            jobs = payload.get("jobs", payload if isinstance(payload, list) else [])
            cron_count = len(jobs) if isinstance(jobs, list) else 0
        except (OSError, json.JSONDecodeError):
            pass
        return {
            "name": profile,
            "display_name": profile.replace("_", " ").replace("-", " ").title(),
            "description": str(metadata.get("description") or ""),
            "home": str(home),
            "model": str(_nested(config, "model", "default") or ""),
            "provider": str(_nested(config, "model", "provider") or ""),
            "workspace": str(_nested(config, "terminal", "cwd") or ""),
            "workspace_key": _path_key(_nested(config, "terminal", "cwd")),
            "skills_count": skills_count,
            "cron_count": cron_count,
            "is_default": profile == self._active_profile(),
            "soul": soul,
            "config_exists": (home / "config.yaml").exists(),
            "env_exists": (home / ".env").exists(),
            "soul_exists": soul_path.exists(),
            "gateway": "unknown",
            "status_error": None,
        }

    def _probe_agent_runtime(self, row: dict[str, Any]) -> None:
        profile = str(row["name"])
        errors: list[str] = []
        try:
            show = self._parse_profile_show(
                self.cli.run_text([self.hermes, "profile", "show", profile], timeout=30)
            )
            if not row.get("model"):
                row["model"] = str(show.get("model") or "")
        except Exception as exc:
            errors.append(str(exc))
        try:
            row["gateway"] = self._normalized_gateway_state(profile)
        except Exception as exc:
            errors.append(str(exc))
            row["gateway"] = "error"
        row["status_error"] = "; ".join(errors) or None

    def agent_get(self, name: str, *, probe_runtime: bool = True) -> dict[str, Any]:
        profile = self._normalize_profile(name)
        row = self._agent_file_snapshot(profile)
        if probe_runtime:
            self._probe_agent_runtime(row)
        return row

    def agent_list(self, *, probe_runtime: bool = True) -> list[dict[str, Any]]:
        rows = [self._agent_file_snapshot(name) for name in self.profile_names()]
        if probe_runtime:
            for row in rows:
                self._probe_agent_runtime(row)
        return rows

    def _set_config(self, profile: str, key: str, value: str) -> str:
        if not str(value).strip():
            raise ValueError(f"{key} cannot be empty")
        return self.cli.run_text(
            self._profile_cli(profile, "config", "set", key, value),
            env=self._env_for(profile),
        )

    def _write_soul(self, profile: str, content: str) -> None:
        if len(content) > 200_000:
            raise ValueError("SOUL.md exceeds 200000 characters")
        home = self._profile_home(profile)
        fd, temp_path = tempfile.mkstemp(prefix="SOUL.", suffix=".tmp", dir=str(home))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            Path(temp_path).replace(home / "SOUL.md")
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass

    def agent_create(self, args: dict[str, Any]) -> dict[str, Any]:
        name = self._normalize_profile(str(args.get("name") or ""))
        if name == "default":
            raise ValueError("default profile already exists")
        command = [self.hermes, "profile", "create", name]
        mode = str(args.get("clone_mode") or "blank").strip().lower()
        source = str(args.get("clone_from") or "").strip().lower()
        if mode not in {"blank", "clone", "clone_all"}:
            raise ValueError("clone_mode must be blank, clone, or clone_all")
        if mode == "clone":
            command.append("--clone")
        elif mode == "clone_all":
            command.append("--clone-all")
        if source:
            self._profile_home(source)
            command += ["--clone-from", source]
            if mode == "blank":
                command.append("--clone")
        description = str(args.get("description") or "").strip()
        if description:
            command += ["--description", description]
        if bool(args.get("no_skills", False)):
            if mode != "blank" or source:
                raise ValueError("no_skills cannot be combined with cloning")
            command.append("--no-skills")
        output = self.cli.run_text(command, timeout=120)
        workspace = str(args.get("workspace") or "").strip()
        provider = str(args.get("provider") or "").strip()
        model = str(args.get("model") or "").strip()
        if workspace:
            self._set_config(name, "terminal.cwd", str(Path(workspace).expanduser()))
        if provider:
            self._set_config(name, "model.provider", provider)
        if model:
            self._set_config(name, "model.default", model)
        if args.get("soul") is not None:
            self._write_soul(name, str(args["soul"]))
        return {"ok": True, "output": output, "agent": self.agent_get(name)}

    def agent_update(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        profile = self._normalize_profile(name)
        self._profile_home(profile)
        new_name = str(args.get("name") or "").strip().lower()
        if new_name and new_name != profile:
            new_name = self._normalize_profile(new_name)
            if profile == "default":
                raise ValueError("default profile cannot be renamed")
            self.cli.run_text([self.hermes, "profile", "rename", profile, new_name], timeout=60)
            profile = new_name
        if args.get("description") is not None:
            self.cli.run_text([
                self.hermes,
                "profile",
                "describe",
                profile,
                "--text",
                str(args.get("description") or ""),
            ])
        if args.get("workspace") is not None:
            workspace = str(args.get("workspace") or ".").strip() or "."
            self._set_config(profile, "terminal.cwd", str(Path(workspace).expanduser()))
        if args.get("provider") is not None and str(args.get("provider") or "").strip():
            self._set_config(profile, "model.provider", str(args["provider"]).strip())
        if args.get("model") is not None and str(args.get("model") or "").strip():
            self._set_config(profile, "model.default", str(args["model"]).strip())
        if args.get("soul") is not None:
            self._write_soul(profile, str(args["soul"]))
        return {"ok": True, "agent": self.agent_get(profile)}

    def _gateway_state(self, profile: str) -> str:
        try:
            text = self.cli.run_text(
                self._profile_cli(profile, "gateway", "status"),
                env=self._env_for(profile),
                timeout=30,
            )
            return text.strip().lower()
        except Exception as exc:
            return f"error: {exc}".lower()

    def _normalized_gateway_state(self, profile: str) -> str:
        state = self._gateway_state(profile)
        if "running" in state and "not running" not in state and "stopped" not in state:
            return "running"
        if any(marker in state for marker in ("not running", "stopped", "no gateway process detected", "recorded process is gone")):
            return "stopped"
        if state.startswith("error:"):
            return "error"
        return "unknown"

    def _verify_gateway_transition(self, profile: str, expected_running: bool, timeout: float = 12.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last = "unknown"
        while time.monotonic() < deadline:
            last = self._gateway_state(profile)
            running = "running" in last and "not running" not in last and "stopped" not in last
            if running == expected_running:
                return {"verified": True, "state": last}
            time.sleep(0.5)
        return {"verified": False, "state": last}

    def agent_action(self, name: str, action: str, value: str | None = None) -> dict[str, Any]:
        profile = self._normalize_profile(name)
        self._profile_home(profile)
        action = str(action or "").strip().lower()
        if action == "use":
            output = self.cli.run_text([self.hermes, "profile", "use", profile])
            return {"ok": True, "action": action, "output": output, "agent": self.agent_get(profile)}
        if action in {"gateway_start", "gateway_stop", "gateway_restart", "gateway_status"}:
            verb = action.split("_", 1)[1]
            output = self.cli.run_text(
                self._profile_cli(profile, "gateway", verb),
                env=self._env_for(profile),
                timeout=90,
            )
            if action == "gateway_status":
                return {"ok": True, "action": action, "output": output, "agent": self.agent_get(profile)}
            transition = self._verify_gateway_transition(profile, expected_running=action != "gateway_stop")
            if not transition["verified"]:
                return {
                    "ok": False,
                    "action": action,
                    "output": output,
                    "warning": "command succeeded but gateway state could not be verified",
                    "gateway_state": transition["state"],
                    "agent": self.agent_get(profile),
                }
            return {"ok": True, "action": action, "output": output, "gateway_state": transition["state"], "agent": self.agent_get(profile)}
        if action == "set_workspace":
            if not value:
                raise ValueError("set_workspace requires value")
            output = self._set_config(profile, "terminal.cwd", str(Path(value).expanduser()))
            return {"ok": True, "action": action, "output": output, "agent": self.agent_get(profile)}
        if action == "export":
            target = Path(value or self.root / "backups" / f"{profile}-profile.tar.gz").expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            output = self.cli.run_text([self.hermes, "profile", "export", profile, "-o", str(target)], timeout=180)
            return {"ok": True, "action": action, "output": output, "path": str(target)}
        raise ValueError("unsupported agent action")

    def agent_delete(self, name: str) -> dict[str, Any]:
        profile = self._normalize_profile(name)
        if profile == "default":
            raise ValueError("default profile cannot be deleted")
        if profile == self._active_profile():
            raise ValueError("active/default-selected profile cannot be deleted; switch profiles first")
        self._profile_home(profile)
        output = self.cli.run_text([self.hermes, "profile", "delete", profile, "--yes"], timeout=120)
        return {"ok": True, "deleted": profile, "output": output}

    def _project_cli(self, profile: str | None, *args: str) -> list[str]:
        return self._profile_cli(profile, "project", *args)

    @staticmethod
    def _parse_project_list(text: str, profile: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        pattern = re.compile(r"^([* ])\s+([^\s]+)\s{2,}(.+?)(?:\s+\[(\d+) folder\(s\)\])?$")
        for line in text.splitlines():
            match = pattern.match(line.rstrip())
            if not match:
                continue
            marker, slug, label, folders = match.groups()
            archived = label.endswith(" (archived)")
            if archived:
                label = label[: -len(" (archived)")]
            rows.append({
                "profile": profile,
                "slug": slug,
                "name": label.strip(),
                "archived": archived,
                "active": marker == "*",
                "folder_count": int(folders or 0),
            })
        return rows

    @staticmethod
    def _parse_project_show(text: str, profile: str) -> dict[str, Any]:
        lines = text.splitlines()
        if not lines:
            return {"profile": profile, "folders": []}
        head = re.match(r"^(\S+)\s+\[([^\]]+)\](\s+\(archived\))?", lines[0].strip())
        result: dict[str, Any] = {"profile": profile, "folders": []}
        if head:
            result.update({"slug": head.group(1), "id": head.group(2), "archived": bool(head.group(3))})
        in_folders = False
        for raw in lines[1:]:
            stripped = raw.strip()
            if stripped == "folders:":
                in_folders = True
                continue
            if in_folders and stripped:
                primary = stripped.startswith("*")
                value = stripped.lstrip("* ").strip()
                match = re.match(r"^(.*?)(?:\s+\(([^()]*)\))?$", value)
                path = match.group(1).strip() if match else value
                label = str(match.group(2) or "") if match else ""
                result["folders"].append({
                    "path": path,
                    "path_key": _path_key(path),
                    "label": label,
                    "is_primary": primary,
                })
                continue
            in_folders = False
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                mapping = {"name": "name", "about": "description", "board": "board", "primary": "primary_path"}
                if key.strip() in mapping:
                    result[mapping[key.strip()]] = value.strip()
        if result.get("primary_path"):
            result["primary_path_key"] = _path_key(result["primary_path"])
        return result

    @staticmethod
    def _associate_agents(project: dict[str, Any], agents: list[dict[str, Any]]) -> list[str]:
        folder_keys = {str(f.get("path_key") or _path_key(f.get("path"))) for f in project.get("folders", [])}
        return [
            str(agent["name"])
            for agent in agents
            if str(agent.get("workspace_key") or _path_key(agent.get("workspace"))) in folder_keys
            and str(agent.get("workspace_key") or _path_key(agent.get("workspace")))
        ]

    def project_get(
        self,
        project: str,
        profile: str | None = None,
        *,
        agents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        p = self._normalize_profile(profile)
        ident = str(project or "").strip()
        if not ident or len(ident) > 128 or any(ch in ident for ch in "\r\n\0"):
            raise ValueError("invalid project reference")
        text = self.cli.run_text(self._project_cli(p, "show", ident), env=self._env_for(p), timeout=30)
        row = self._parse_project_show(text, p)
        row["agents"] = self._associate_agents(row, agents if agents is not None else self.agent_list(probe_runtime=False))
        return row

    def project_list(
        self,
        profile: str | None = None,
        include_archived: bool = True,
        *,
        agents: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        profiles = [self._normalize_profile(profile)] if profile else self.profile_names()
        snapshot = agents if agents is not None else self.agent_list(probe_runtime=False)
        rows: list[dict[str, Any]] = []
        for p in profiles:
            args = ["list"] + (["--all"] if include_archived else [])
            text = self.cli.run_text(self._project_cli(p, *args), env=self._env_for(p), timeout=30)
            for listed in self._parse_project_list(text, p):
                detail = self.project_get(listed["slug"], p, agents=snapshot)
                rows.append({**listed, **detail})
        return rows

    def project_create(self, args: dict[str, Any]) -> dict[str, Any]:
        profile = self._normalize_profile(str(args.get("profile") or "default"))
        self._profile_home(profile)
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("project name is required")
        command = self._project_cli(profile, "create", name)
        folders = args.get("folders") or []
        if isinstance(folders, str):
            folders = [folders]
        command.extend(str(folder).strip() for folder in folders if str(folder or "").strip())
        for key, flag in (("slug", "--slug"), ("primary", "--primary"), ("description", "--description"), ("icon", "--icon"), ("color", "--color"), ("board", "--board")):
            value = str(args.get(key) or "").strip()
            if value:
                command += [flag, value]
        if bool(args.get("use", False)):
            command.append("--use")
        output = self.cli.run_text(command, env=self._env_for(profile), timeout=60)
        slug = str(args.get("slug") or "").strip()
        if not slug:
            match = re.search(r"Created project\s+(\S+)\s+\(", output)
            slug = match.group(1) if match else name
        project = self.project_get(slug, profile)
        agent = str(args.get("agent") or "").strip()
        if agent:
            primary = str(project.get("primary_path") or "")
            if not primary:
                raise ValueError("cannot assign workspace agent: project has no primary folder")
            self._set_config(agent, "terminal.cwd", primary)
            project = self.project_get(slug, profile)
        return {"ok": True, "output": output, "project": project}

    def project_update(self, project: str, profile: str | None, args: dict[str, Any]) -> dict[str, Any]:
        p = self._normalize_profile(profile)
        current = self.project_get(project, p)
        ident = str(current.get("slug") or project)
        outputs: list[str] = []
        if args.get("name") is not None and str(args.get("name") or "").strip():
            outputs.append(self.cli.run_text(self._project_cli(p, "rename", ident, str(args["name"]).strip()), env=self._env_for(p)))
        if args.get("primary") is not None and str(args.get("primary") or "").strip():
            outputs.append(self.cli.run_text(self._project_cli(p, "set-primary", ident, str(args["primary"]).strip()), env=self._env_for(p)))
        if args.get("board") is not None:
            command = self._project_cli(p, "bind-board", ident)
            board = str(args.get("board") or "").strip()
            if board:
                command.append(board)
            outputs.append(self.cli.run_text(command, env=self._env_for(p)))
        for folder in args.get("add_folders") or []:
            if str(folder or "").strip():
                outputs.append(self.cli.run_text(self._project_cli(p, "add-folder", ident, str(folder).strip()), env=self._env_for(p)))
        for folder in args.get("remove_folders") or []:
            if str(folder or "").strip():
                outputs.append(self.cli.run_text(self._project_cli(p, "remove-folder", ident, str(folder).strip()), env=self._env_for(p)))
        agent = str(args.get("agent") or "").strip()
        if agent:
            refreshed = self.project_get(ident, p)
            primary = str(refreshed.get("primary_path") or "")
            if not primary:
                raise ValueError("cannot assign workspace agent: project has no primary folder")
            outputs.append(self._set_config(agent, "terminal.cwd", primary))
        unsupported = [key for key in ("description", "icon", "color") if args.get(key) is not None]
        if unsupported:
            raise ValueError(
                "Hermes project CLI does not currently expose editing for: " + ", ".join(unsupported)
            )
        return {"ok": True, "output": "\n".join(x for x in outputs if x), "project": self.project_get(ident, p)}

    def project_action(self, project: str, profile: str | None, action: str, value: str | None = None) -> dict[str, Any]:
        p = self._normalize_profile(profile)
        current = self.project_get(project, p)
        ident = str(current.get("slug") or project)
        action = str(action or "").strip().lower()
        if action in {"use", "archive", "restore"}:
            output = self.cli.run_text(self._project_cli(p, action, ident), env=self._env_for(p))
        elif action in {"add_folder", "remove_folder", "set_primary"}:
            if not value:
                raise ValueError(f"{action} requires value")
            verb = {"add_folder": "add-folder", "remove_folder": "remove-folder", "set_primary": "set-primary"}[action]
            output = self.cli.run_text(self._project_cli(p, verb, ident, value), env=self._env_for(p))
        elif action == "bind_board":
            command = self._project_cli(p, "bind-board", ident)
            if value:
                command.append(value)
            output = self.cli.run_text(command, env=self._env_for(p))
        elif action == "assign_agent":
            if not value:
                raise ValueError("assign_agent requires an agent name")
            primary = str(current.get("primary_path") or "")
            if not primary:
                raise ValueError("project has no primary folder")
            output = self._set_config(value, "terminal.cwd", primary)
        else:
            raise ValueError("unsupported project action")
        return {"ok": True, "action": action, "output": output, "project": self.project_get(ident, p)}

    def snapshot(self, *, include_archived: bool = True) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        agents = self.agent_list(probe_runtime=True)
        for agent in agents:
            if agent.get("status_error"):
                errors.append({"scope": f"agent:{agent['name']}", "message": str(agent["status_error"])})
        projects: list[dict[str, Any]] = []
        for profile in self.profile_names():
            try:
                projects.extend(self.project_list(profile, include_archived=include_archived, agents=agents))
            except Exception as exc:
                errors.append({"scope": f"projects:{profile}", "message": str(exc)})
        active_projects = [p for p in projects if not p.get("archived")]
        running = [a for a in agents if str(a.get("gateway") or "").lower().startswith("running")]
        return {
            "counts": {
                "agents": len(agents),
                "running_agents": len(running),
                "projects": len(active_projects),
                "archived_projects": sum(1 for p in projects if p.get("archived")),
            },
            "agents": agents,
            "projects": projects,
            "active_profile": self._active_profile(),
            "partial": bool(errors),
            "errors": errors,
        }

    def overview(self) -> dict[str, Any]:
        return self.snapshot(include_archived=True)
