"""Strict JSON schemas exposed to Hermes for the extensions plugin."""

WECHAT_STATUS = {
    "name": "wechat_status",
    "description": "Check whether Windows WeChat is running and inspectable.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
WECHAT_LIST_CHATS = {
    "name": "wechat_list_chats",
    "description": "List visible WeChat conversations with best-effort unread state.",
    "parameters": {
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}},
        "additionalProperties": False,
    },
}
WECHAT_GET_UNREAD_CHATS = {
    "name": "wechat_get_unread_chats",
    "description": "List conversations that appear unread.",
    "parameters": {
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}},
        "additionalProperties": False,
    },
}
WECHAT_GET_MESSAGES = {
    "name": "wechat_get_messages",
    "description": "Open an exact conversation and read newest visible messages.",
    "parameters": {
        "type": "object",
        "properties": {
            "chat": {"type": "string", "minLength": 1, "maxLength": 256},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        },
        "required": ["chat"],
        "additionalProperties": False,
    },
}
WECHAT_SEND_MESSAGE = {
    "name": "wechat_send_message",
    "description": "Send text to an exact WeChat conversation with fail-closed target verification.",
    "parameters": {
        "type": "object",
        "properties": {
            "chat": {"type": "string", "minLength": 1, "maxLength": 256},
            "text": {"type": "string", "minLength": 1, "maxLength": 4000},
            "dry_run": {"type": "boolean", "default": False},
        },
        "required": ["chat", "text"],
        "additionalProperties": False,
    },
}

TASK_CENTER_OVERVIEW = {
    "name": "task_center_overview",
    "description": "Return fleet-wide Hermes profile, Cron, Kanban, and execution summaries.",
    "parameters": {
        "type": "object",
        "properties": {"profile": {"type": "string"}, "include_completed": {"type": "boolean", "default": False}},
        "additionalProperties": False,
    },
}
TASK_CENTER_UPCOMING = {
    "name": "task_center_upcoming",
    "description": "List upcoming Hermes tasks with recurring Cron occurrences expanded.",
    "parameters": {
        "type": "object",
        "properties": {
            "hours": {"type": "integer", "minimum": 1, "maximum": 2160, "default": 168},
            "profile": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
        },
        "additionalProperties": False,
    },
}
TASK_CENTER_CREATE = {
    "name": "task_center_create",
    "description": "Create a native Hermes Cron or Kanban task.",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["cron", "kanban"]},
            "name": {"type": "string", "minLength": 1, "maxLength": 256},
            "prompt": {"type": "string", "maxLength": 20000},
            "schedule": {"type": "string", "maxLength": 256},
            "profile": {"type": "string"},
            "priority": {"type": "integer", "minimum": 0, "maximum": 100},
            "deliver": {"type": "string", "maxLength": 128},
        },
        "required": ["type", "name"],
        "additionalProperties": False,
    },
}
TASK_CENTER_UPDATE = {
    "name": "task_center_update",
    "description": "Update a native Hermes Cron or Kanban task.",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["cron", "kanban"]},
            "id": {"type": "string", "minLength": 1},
            "name": {"type": "string", "minLength": 1, "maxLength": 256},
            "prompt": {"type": "string", "maxLength": 20000},
            "schedule": {"type": "string", "maxLength": 256},
            "profile": {"type": "string"},
            "priority": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": ["type", "id"],
        "additionalProperties": False,
    },
}
TASK_CENTER_ACTION = {
    "name": "task_center_action",
    "description": "Pause, resume, run or remove Cron; assign/archive Kanban.",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["cron", "kanban"]},
            "id": {"type": "string", "minLength": 1},
            "action": {"type": "string", "enum": ["pause", "resume", "run", "remove", "assign", "archive"]},
            "value": {"type": "string"},
            "profile": {"type": "string"},
        },
        "required": ["type", "id", "action"],
        "additionalProperties": False,
    },
}
TASK_CENTER_HISTORY = {
    "name": "task_center_history",
    "description": "Read native execution history for Cron or Kanban.",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["cron", "kanban"]},
            "id": {"type": "string", "minLength": 1},
            "profile": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
        },
        "required": ["type", "id"],
        "additionalProperties": False,
    },
}

MANAGEMENT_OVERVIEW = {
    "name": "management_overview",
    "description": "Return agents, projects, partial-load errors, task counts, and the next seven days of work.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
AGENT_LIST = {
    "name": "agent_list",
    "description": "List Hermes agents (native profiles) with model, workspace, gateway and task metadata.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
AGENT_GET = {
    "name": "agent_get",
    "description": "Get one Hermes agent/profile including description, model, workspace and SOUL content.",
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 64}},
        "required": ["name"],
        "additionalProperties": False,
    },
}
AGENT_CREATE = {
    "name": "agent_create",
    "description": "Create a native Hermes profile/agent. Supports blank, config clone, or clone-all modes.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$"},
            "description": {"type": "string", "maxLength": 2000},
            "clone_mode": {"type": "string", "enum": ["blank", "clone", "clone_all"], "default": "blank"},
            "clone_from": {"type": "string"},
            "no_skills": {"type": "boolean", "default": False},
            "workspace": {"type": "string", "maxLength": 4096},
            "model": {"type": "string", "maxLength": 512},
            "provider": {"type": "string", "maxLength": 128},
            "soul": {"type": "string", "maxLength": 200000},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}
AGENT_UPDATE = {
    "name": "agent_update",
    "description": "Edit a Hermes agent/profile name, role, workspace, model/provider or SOUL.",
    "parameters": {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "minLength": 1},
            "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$"},
            "description": {"type": "string", "maxLength": 2000},
            "workspace": {"type": "string", "maxLength": 4096},
            "model": {"type": "string", "maxLength": 512},
            "provider": {"type": "string", "maxLength": 128},
            "soul": {"type": "string", "maxLength": 200000},
        },
        "required": ["agent"],
        "additionalProperties": False,
    },
}
AGENT_ACTION = {
    "name": "agent_action",
    "description": "Operate on an agent. Destructive delete and gateway restart are intentionally not exposed to autonomous tool use.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "action": {"type": "string", "enum": ["use", "gateway_start", "gateway_stop", "gateway_status", "set_workspace", "export"]},
            "value": {"type": "string"},
        },
        "required": ["name", "action"],
        "additionalProperties": False,
    },
}
PROJECT_LIST = {
    "name": "project_list",
    "description": "List native Hermes projects across profiles or within one profile.",
    "parameters": {
        "type": "object",
        "properties": {"profile": {"type": "string"}, "include_archived": {"type": "boolean", "default": True}},
        "additionalProperties": False,
    },
}
PROJECT_GET = {
    "name": "project_get",
    "description": "Get a native Hermes project and computed workspace agents whose terminal.cwd matches a project folder.",
    "parameters": {
        "type": "object",
        "properties": {"project": {"type": "string", "minLength": 1}, "profile": {"type": "string", "default": "default"}},
        "required": ["project"],
        "additionalProperties": False,
    },
}
PROJECT_CREATE = {
    "name": "project_create",
    "description": "Create a native Hermes project with folders, primary repo, board and optional workspace-agent assignment.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 256},
            "profile": {"type": "string"},
            "slug": {"type": "string", "maxLength": 128},
            "folders": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            "primary": {"type": "string", "maxLength": 4096},
            "description": {"type": "string", "maxLength": 2000},
            "icon": {"type": "string", "maxLength": 128},
            "color": {"type": "string", "maxLength": 64},
            "board": {"type": "string", "maxLength": 128},
            "use": {"type": "boolean", "default": False},
            "agent": {"type": "string"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}
PROJECT_UPDATE = {
    "name": "project_update",
    "description": "Update fields supported by Hermes project CLI: name, folders, primary repo, board, or workspace agent.",
    "parameters": {
        "type": "object",
        "properties": {
            "project": {"type": "string", "minLength": 1},
            "profile": {"type": "string"},
            "name": {"type": "string", "minLength": 1, "maxLength": 256},
            "primary": {"type": "string", "maxLength": 4096},
            "board": {"type": "string", "maxLength": 128},
            "add_folders": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            "remove_folders": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            "agent": {"type": "string"},
        },
        "required": ["project"],
        "additionalProperties": False,
    },
}
PROJECT_ACTION = {
    "name": "project_action",
    "description": "Operate on a native Hermes project or set its workspace agent.",
    "parameters": {
        "type": "object",
        "properties": {
            "project": {"type": "string", "minLength": 1},
            "profile": {"type": "string"},
            "action": {"type": "string", "enum": ["use", "archive", "restore", "add_folder", "remove_folder", "set_primary", "bind_board", "assign_agent"]},
            "value": {"type": "string"},
        },
        "required": ["project", "action"],
        "additionalProperties": False,
    },
}
