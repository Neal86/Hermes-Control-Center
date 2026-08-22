from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchemaProbe:
    fingerprint: str
    capabilities: tuple[str, ...]


def _shape(connection: sqlite3.Connection) -> list[str]:
    rows: list[str] = []
    tables = [row[0] for row in connection.execute("select name from sqlite_master where type='table' order by name")]
    for table in tables:
        columns = connection.execute(f'pragma table_info("{table}")').fetchall()
        rows.append(table + "|" + "|".join(f"{col[1]}:{col[2]}" for col in columns))
    return rows


def probe_sqlite(paths: list[Path]) -> SchemaProbe:
    shapes: list[str] = []
    names: set[str] = set()
    columns: set[str] = set()
    for path in paths:
        with sqlite3.connect(path) as connection:
            shape = _shape(connection)
            shapes.extend(f"{path.name}:{row}" for row in shape)
            for row in shape:
                parts = row.split("|")
                names.add(parts[0])
                columns.update(piece.split(":", 1)[0] for piece in parts[1:])
    capabilities: list[str] = []
    if "SessionTable" in names and {"username", "unread_count", "last_timestamp"} <= columns:
        capabilities.append("sessions")
    if any(name.startswith("Msg_") for name in names) and {"server_id", "sort_seq", "real_sender_id", "message_content"} <= columns:
        capabilities.extend(["messages", "stable_message_id", "sender_id"] )
    if "contact" in names and {"username", "nick_name", "remark"} <= columns:
        capabilities.append("contacts")
    digest = hashlib.sha256("\n".join(sorted(shapes)).encode("utf-8")).hexdigest()
    return SchemaProbe(digest, tuple(sorted(set(capabilities))))
