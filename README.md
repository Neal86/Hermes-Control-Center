# Hermes Control Center

Standalone control center and extensions for **NousResearch/hermes-agent**. This repository does not depend on OpenAkita runtime, APIs, agents, or databases.

Repository: `Neal86/Hermes-Control-Center`

Current package version: **0.5.1**.

## One-click Windows Setup

Download the repository ZIP, extract it, then double-click:

```text
Setup.cmd
```

Or run directly in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Setup-Hermes-Control-Center.ps1
```

The Setup menu provides:

1. **Install / update everything** — installs Hermes if missing, optionally updates an existing Hermes install, then installs/updates Control Center.
2. **Update Hermes only** — updates the detected Hermes installation without reinstalling Control Center.
3. **Install / update Control Center only** — keeps the current Hermes version and refreshes the plugin.
4. **Repair Control Center** — runs preflight and performs a transactional reinstall.
5. **Open Hermes Dashboard** — launches `hermes dashboard`.

Setup detects the existing Hermes install type. A `uv tool` installation is updated with `uv tool upgrade hermes-agent`; the official Windows installation is updated through the current official Hermes Windows installer. Unknown/external Hermes installations are never overwritten automatically.

Setup preserves the existing Hermes home and does not delete Profiles/Agents, Skills, Cron state, plugin-data, Provider settings, or resource bindings.

## Control Center

`hermes dashboard` loads the Management Center with these sections:

- **Overview** — runtime/Agent/task status and upcoming work.
- **Agents** — Hermes Profile create/clone/edit/use/export/delete, workspace, Provider, model, SOUL and Gateway controls.
- **Projects** — native Hermes Project management when supported by the installed Hermes build.
- **Tasks** — Cron and Kanban management across Agents.
- **WeChat** — Windows WeChat health, conversation inspection and guarded dry-run controls.
- **Providers** — configure Provider endpoint/model/credential settings used by Agents.
- **Resources** — discover running Windows WeChat, Chrome and Edge resources and bind them to specific Agents.

## Agent resource isolation

Control Center treats desktop resource bindings as an authorization boundary, not a preference.

- A WeChat or browser resource is exclusively assigned to one Agent.
- An Agent may only use resources explicitly bound to that Agent.
- No binding means access is denied.
- An offline bound resource returns an explicit unavailable error.
- A non-attachable browser is visible in Resources but cannot be used for browser automation.
- There is no fallback to another Agent's WeChat/browser.
- Binding WeChat does not disable `computer_use`, `clarify`, or general web automation. Those capabilities remain available; browser automation is still scoped to the Agent-bound browser, while Desktop WeChat send/receive stays on the bound Gateway platform.

Resource state is persisted under:

```text
~/.hermes/plugin-data/hermes-extensions/resources/
    resources.json
    bindings.json
```

## Windows WeChat Desktop

The plugin registers local Windows WeChat tools plus a Hermes Gateway platform. Automation uses Windows UI Automation rather than fixed coordinates and verifies the bound HWND/PID before operations.

Registered tools include:

- `wechat_status`
- `wechat_list_chats`
- `wechat_get_unread_chats`
- `wechat_get_messages`
- `wechat_send_message`
- `resource_list`
- `bound_browser`

WeChat tool calls require an Agent identity and resolve only that Agent's bound WeChat resource. The platform adapter also resolves the current Hermes Profile/Agent binding before polling or sending.

## Browser binding

Resources detects running Chrome and Edge windows, including profile/user-data-dir information when available. Browsers started with a Chrome DevTools endpoint are marked `ready`; ordinary running browsers without an attachable CDP endpoint are marked `not_attachable`.

Hermes browser tools are protected by a plugin `pre_tool_call` policy hook. For browser tools, the hook requires a browser bound to the active Agent. When the bound browser exposes a CDP port, the plugin sets `BROWSER_CDP_URL` for the call so Hermes targets the assigned browser instead of selecting another instance.

## Providers

Provider configuration is managed separately from Agent resource bindings. Each Agent can keep its own Hermes Provider/model configuration while credentials remain stored under the Agent/Profile Hermes home rather than being returned by Control Center APIs.

## Manual plugin install

If Hermes is already installed and you do not want to use the unified Setup:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\doctor.ps1 -Preflight
.\install.ps1
.\doctor.ps1 -Installed
```

The plugin installer detects the actual Hermes Python interpreter, installs Windows dependencies, stages the plugin, builds the Dashboard bundle, backs up the existing plugin/platform/config, atomically replaces the plugin, enables it, and rolls back on installation failure.

## Doctor modes

```powershell
.\doctor.ps1 -Preflight
.\doctor.ps1 -Preflight -Json
.\doctor.ps1 -Installed
.\doctor.ps1 -Installed -Json
```

## Release package

Release builds produce:

```text
Hermes-Control-Center-v0.5.1.zip
Hermes-Control-Center-v0.5.1.zip.sha256
```

The ZIP includes the one-click Setup, plugin installer, Dashboard source/bundle, Provider manager, resource discovery/bindings/policy, WeChat runtime/platform and all runtime files required for installation. Repository automation and tests are excluded from the packaged plugin tree.

## Security notes

- Desktop resource bindings fail closed.
- Agent browser/WeChat access is restricted to explicitly bound resources.
- Default and active Profiles are protected from deletion.
- Human Dashboard destructive/runtime actions use explicit confirmation UI.
- Profile/SOUL paths are validated against traversal.
- Provider credentials are never returned in normal Control Center list responses.
- WeChat sends fail closed when the bound window, exact target conversation or UI lock cannot be verified.
- Keep Hermes Dashboard on localhost or behind trusted authentication/network controls.
