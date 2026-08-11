# Hermes Control Center

Standalone control center and extensions for **NousResearch/hermes-agent**. This repository does not depend on the OpenAkita runtime, APIs, agents, or databases.

Repository: `Neal86/Hermes-Control-Center`

Current package version: **0.5.1**.

## Hermes Management Center v0.5.1

`hermes dashboard` gets one complete Management Center with five tabs:

- **Overview** — Agent/runtime/task counters, upcoming work, Project capability state, persisted WeChat Gateway health and scoped partial-load errors.
- **Agents** — native Hermes Profile create/clone/rename/edit/use/export/delete, workspace/model/provider/SOUL management and Gateway start/stop/restart/status.
- **Projects** — native Hermes Project create/use/archive/restore, folder add/remove/set-primary, board binding and Workspace Agent assignment. Unsupported Hermes builds show an explicit compatibility state instead of exposing failing controls.
- **Tasks** — searchable/filterable Cron and Kanban management with create/edit, Cron pause/resume/run/delete, Kanban assignment/priority/archive, upcoming occurrences and execution history.
- **WeChat** — Gateway health, manual desktop checks, partial-result reporting, recent/unread chats and a fail-closed dry-run test that never presses Enter.

### v0.5.1 UX polish

The frontend is maintained as small source modules (`api.js`, `components.js`, `app.js`, `index.js`) and deterministically bundled into the single `dashboard/dist/index.js` file required by Hermes. Installation and Release builds both run `dashboard/build_bundle.py`, so Hermes still loads one normal plugin bundle.

User-facing UX improvements:

- Entering the **WeChat** tab reads persisted health only and never automatically focuses or scans the Windows WeChat UI.
- **Check desktop** is an explicit user action and uses partial-result handling, so a failed scan no longer hides successful desktop status or chat results.
- The top **Refresh** button is context-aware: Tasks refreshes task state, WeChat refreshes health only, and other tabs refresh Management state.
- Visible pages auto-refresh lightweight state (`30s` for Management/Tasks, `15s` for WeChat health) only while the document is visible. Auto-refresh never runs WeChat UI Automation.
- Dialogs trap keyboard focus, support Escape/backdrop close, restore focus to the launching control and lock background scrolling.
- Native browser `confirm()` prompts were replaced by a consistent in-product confirmation dialog.
- Agent, Project and Task edit/create dialogs protect unsaved changes before closing.
- Action buttons expose granular busy labels/states and block duplicate mutations while an action is running.
- Mobile controls use touch-friendly targets and wrapped action rows.
- Focus-visible styling is explicit for keyboard navigation.

## Windows WeChat Desktop

The plugin registers local Windows WeChat tools and a Gateway platform. Automation uses Windows UI Automation rather than fixed coordinates and fails closed before outbound sends when the exact target conversation cannot be proven.

Registered tools:

- `wechat_status`
- `wechat_list_chats`
- `wechat_get_unread_chats`
- `wechat_get_messages`
- `wechat_send_message`

For known group conversations, configure exact names with `WECHAT_DESKTOP_GROUP_CHATS` (comma separated) or platform `extra.group_chats`. Those conversations enter Hermes with `chat_type="group"`; other chats remain `dm` unless explicitly configured.

The hardened `wechat/runtime.py` serializes UI operations across threads/processes. The exclusive transaction covers chat selection, exact-target verification, paste, final verification, Enter/dry-run cleanup and duplicate-send state. Lock timeout fails closed.

Gateway polling persists `healthy`, `degraded`, `failed` or `stopped` state plus consecutive failures, last error and last successful poll. Repeated UIA failures back off exponentially; recovery resets health.

## Hermes Task Center

Task Center v3 reads native per-profile Cron state/history plus Hermes Kanban surfaces and uses Hermes CLI for mutations.

Upcoming scheduling is globally fair: each scheduled task gets first-occurrence visibility before high-frequency recurring jobs fill the remaining result budget. Cron execution status is queried in batches with one SQLite connection per Profile and only the latest run per job returned.

## Agents and Projects

Hermes Profiles are treated as Agents; Hermes Projects remain native profile-scoped Projects. The extension does not create a second Agent, Project, scheduler or task database.

When `hermes project` is absent (as observed on Hermes v0.16.0), Project API reads return `supported: false`, mutations return structured 409 responses, Project model tools are not registered, and the Dashboard shows the unsupported state without exposing create controls. Agents, Tasks and WeChat remain available.

## Install on Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\doctor.ps1 -Preflight
.\install.ps1
.\doctor.ps1 -Installed
```

The installer detects the actual Hermes Python interpreter, verifies dependencies, stages the plugin, builds the modular Dashboard bundle, compiles Python, backs up the current extension/WeChat platform/config, atomically replaces code, enables plugins and runs installed doctor checks. Failed upgrades restore plugin files and Hermes plugin configuration.

A first installation or Dashboard backend Python change should restart only `hermes dashboard`. Frontend-only updates can use Dashboard rescan. WeChat platform/runtime Python changes require restarting the relevant Gateway.

## Doctor modes

```powershell
.\doctor.ps1 -Preflight
.\doctor.ps1 -Preflight -Json
.\doctor.ps1 -Installed
.\doctor.ps1 -Installed -Json
```

The default mode is `-Installed`.

## Release package

The release workflow builds:

```text
Hermes-Control-Center-v0.5.1.zip
Hermes-Control-Center-v0.5.1.zip.sha256
```

The archive contains only this standalone Hermes extension tree, excludes tests and repository automation files, includes modular Dashboard source for maintainability and includes the generated single `dashboard/dist/index.js` plus `dashboard/dist/style.css` consumed by Hermes.

## Validation

CI covers Python compilation, Ruff, pytest, syntax checks for each Dashboard source module and the generated bundle, v0.5.1 UI/UX contract tests, no-auto-UIA WeChat tab behavior, context-aware refresh, visibility-aware auto-refresh, partial desktop results, focus trapping/restoration, custom confirmation dialogs, unsaved-change protection, mobile touch targets, strict Dashboard request bodies, Project compatibility behavior, fair Task scheduling, batched Cron history, cross-process WeChat locking, polling health/backoff, Windows installer syntax and Release ZIP isolation/SHA256 generation.

A real WeChat acceptance test still requires native Windows with a logged-in WeChat client. CI cannot substitute for device-level UI Automation testing.

## Security notes

- Default and active Profiles are protected from deletion.
- Autonomous Agent tools do not expose Profile deletion or Gateway restart.
- Human Dashboard destructive/runtime actions use explicit confirmation UI.
- Profile/SOUL paths are validated against traversal.
- Provider credentials/API keys are not exposed by Management Center.
- WeChat outbound sends fail closed when exact-target verification or the cross-process UI lock cannot be obtained.
- The Management Center exposes only a WeChat dry-run test, not an unguarded real-send UI.
- Keep Hermes Dashboard on localhost or behind trusted authentication/network controls.
