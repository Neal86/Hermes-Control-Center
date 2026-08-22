from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import hmac
import os
import re
import sqlite3
import struct
import tempfile
import time
from pathlib import Path
from typing import Iterable

from ..account_matcher import match_account
from ..base import BackendStatus, BackendUnavailable, ReceiverBackend
from ..discovery import WeChatProcessInfo, account_directories
from ..schema_probe import probe_sqlite
from ...message_model import WeChatMessageEvent

_PAGE_SIZE = 4096
_RESERVE_SIZE = 80
_WAL_FRAME_SIZE = 24 + _PAGE_SIZE
_GLOBAL_CONFIG = b"global_config"
_KEY_PATTERN = bytes.fromhex(
    "83ec404889d64889cb0f57c00f1142100f11024c8bb1c80200004883b9d002000010"
    "7209488b9bb8020000eb074881c3b80200004d85f60f880a0200004983fe10736d4c"
    "89761048c746180f0000000f10030f110648b8"
)
_KEY_VERIFY = (
    bytes.fromhex("488944242048b8"),
    bytes.fromhex("488944242848b8"),
    bytes.fromhex("488944243048b8"),
)


class _ModuleEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD), ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wt.DWORD), ("hModule", ctypes.c_void_p), ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * 260),
    ]


def _kernel32():
    if os.name != "nt":
        raise BackendUnavailable("WeChat encrypted DB inspection requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    return kernel32


def _module_info(pid: int, module_name: str = "weixin.dll") -> tuple[int, int, str]:
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(0x18, int(pid))
    invalid = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid:
        raise BackendUnavailable("Unable to enumerate WeChat modules")
    try:
        entry = _ModuleEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Module32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szModule.lower() == module_name.lower():
                return int(entry.modBaseAddr or 0), int(entry.modBaseSize), str(entry.szExePath)
            entry.dwSize = ctypes.sizeof(entry)
            ok = kernel32.Module32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    raise BackendUnavailable(f"{module_name} was not found in the bound WeChat process")


def _read_memory(handle, address: int, size: int) -> bytes:
    kernel32 = _kernel32()
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(read)):
        raise BackendUnavailable("Unable to read bound WeChat process memory")
    return buffer.raw[: read.value]


def _remote_string(handle, address: int) -> str:
    size_raw = _read_memory(handle, address + 16, 8)
    length = struct.unpack("<Q", size_raw)[0]
    if not 0 < length < 4096:
        return ""
    if length <= 15:
        data = _read_memory(handle, address, length)
    else:
        pointer = struct.unpack("<Q", _read_memory(handle, address, 8))[0]
        data = _read_memory(handle, pointer, length)
    return data.decode("utf-8", errors="replace")


def _remote_bytes(handle, address: int) -> bytes:
    length = struct.unpack("<Q", _read_memory(handle, address + 16, 8))[0]
    if not 0 < length <= 1024:
        raise BackendUnavailable("Unexpected WeChat cipher material size")
    capacity = struct.unpack("<I", _read_memory(handle, address + 24, 4))[0]
    if (capacity | 0xF) == 0xF:
        return _read_memory(handle, address, length)
    pointer = struct.unpack("<Q", _read_memory(handle, address, 8))[0]
    return _read_memory(handle, pointer, length)


def _xor_material(module_path: str) -> bytes:
    image = Path(module_path).read_bytes()
    offset = image.find(_KEY_PATTERN)
    if offset < 0:
        raise BackendUnavailable("Unknown WeChat key layout; falling back to UI receiver")
    encoded = image[offset + len(_KEY_PATTERN) : offset + len(_KEY_PATTERN) + 200].hex()
    material = ""
    for marker in _KEY_VERIFY:
        if len(encoded) < 30 or encoded[16:30] != marker.hex():
            raise BackendUnavailable("WeChat key-layout verification failed")
        material += encoded[:16]
        encoded = encoded[30:]
    if len(encoded) < 16:
        raise BackendUnavailable("Incomplete WeChat key material")
    material += encoded[:16]
    return bytes.fromhex(material)


def extract_process_identity(info: WeChatProcessInfo) -> tuple[str, bytes]:
    """Read only the bound process identity/key material; never inject or mutate WeChat."""
    base, size, module_path = _module_info(info.pid)
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(0x0410, False, int(info.pid))
    if not handle:
        raise BackendUnavailable("Unable to open bound WeChat process for read-only inspection")
    try:
        image = _read_memory(handle, base, size)
        landmark = -1
        for offset in range(len(image) - 8, 16, -8):
            if struct.unpack_from("<I", image, offset)[0] != len(_GLOBAL_CONFIG):
                continue
            capacity = struct.unpack_from("<I", image, offset + 8)[0]
            if capacity and (capacity | 0xF) == 0xF and image[offset - 16 : offset - 3] == _GLOBAL_CONFIG:
                landmark = offset
                break
        if landmark < 0:
            raise BackendUnavailable("WeChat global configuration layout is unknown")
        first = struct.unpack("<Q", _read_memory(handle, base + landmark - 0x138, 8))[0]
        config = struct.unpack("<Q", _read_memory(handle, first + 0x68, 8))[0]
        if not 0x10000 <= config < 0x800000000000:
            raise BackendUnavailable("Invalid WeChat configuration pointer")
        wxid = _remote_string(handle, config + 0x48).strip()
        cipher = _remote_bytes(handle, config + 0x2B8)
        material = _xor_material(module_path)
        if not wxid or len(cipher) != len(material):
            raise BackendUnavailable("Unable to validate WeChat account identity/key material")
        return wxid, bytes(left ^ right for left, right in zip(cipher, material))
    finally:
        kernel32.CloseHandle(handle)


def _derive_key(master_key: bytes, first_page: bytes) -> bytes:
    if len(first_page) < 16:
        raise BackendUnavailable("WeChat DB is too small")
    return hashlib.pbkdf2_hmac("sha512", master_key, first_page[:16], 256000, dklen=32)


def _verify_key(db_path: Path, key: bytes) -> bool:
    try:
        page = db_path.read_bytes()[:_PAGE_SIZE]
        if len(page) < _PAGE_SIZE:
            return False
        mac_salt = bytes(value ^ 0x3A for value in page[:16])
        mac_key = hashlib.pbkdf2_hmac("sha512", key, mac_salt, 2, dklen=32)
        data = page[16 : _PAGE_SIZE - _RESERVE_SIZE + 16] + struct.pack("<I", 1)
        return hmac.compare_digest(hmac.new(mac_key, data, hashlib.sha512).digest(), page[_PAGE_SIZE - 64 : _PAGE_SIZE])
    except OSError:
        return False


def _aes_decrypt(key: bytes, page: bytes, page_no: int) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise BackendUnavailable("Hermes runtime is missing cryptography support") from exc
    iv = page[_PAGE_SIZE - _RESERVE_SIZE : _PAGE_SIZE - _RESERVE_SIZE + 16]
    encrypted = page[16 : _PAGE_SIZE - _RESERVE_SIZE] if page_no == 1 else page[: _PAGE_SIZE - _RESERVE_SIZE]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = decryptor.update(encrypted) + decryptor.finalize()
    if page_no == 1:
        plain = b"SQLite format 3\x00" + plain
    return plain + bytes(_RESERVE_SIZE)


def _decrypt_database(source: Path, destination: Path, key: bytes) -> None:
    with source.open("rb") as src, destination.open("wb") as dst:
        page_no = 1
        while True:
            page = src.read(_PAGE_SIZE)
            if not page:
                break
            if len(page) < _PAGE_SIZE:
                page += bytes(_PAGE_SIZE - len(page))
            dst.write(_aes_decrypt(key, page, page_no))
            page_no += 1
    wal = Path(str(source) + "-wal")
    if not wal.is_file() or wal.stat().st_size <= 32:
        return
    with wal.open("rb") as src, destination.open("r+b") as dst:
        header = src.read(32)
        salt = header[16:24]
        while True:
            frame = src.read(24)
            if len(frame) < 24:
                break
            page = src.read(_PAGE_SIZE)
            if len(page) < _PAGE_SIZE:
                break
            if frame[8:16] != salt:
                continue
            page_no = struct.unpack(">I", frame[:4])[0]
            if page_no <= 0:
                continue
            dst.seek((page_no - 1) * _PAGE_SIZE)
            dst.write(_aes_decrypt(key, page, page_no))


def _decode(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8").strip("\x00")
        except UnicodeDecodeError:
            return ""
    return str(value)


def _container_text(value) -> str:
    """Recover readable UTF-8 text from WCDB message containers; fail closed otherwise."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip("\x00")
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return str(value)
    content = bytes(value)
    try:
        direct = content.decode("utf-8").strip("\x00")
        if direct and sum(ch.isprintable() for ch in direct) / max(1, len(direct)) >= 0.8:
            return direct
    except UnicodeDecodeError:
        pass
    offsets = [10] + [index for index in range(min(16, len(content))) if index != 10]
    for offset in offsets:
        chunk = content[offset:]
        marker = chunk.find(b"\x01\x00")
        if marker >= 0:
            chunk = chunk[:marker]
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+", "", text).strip()
        if not text:
            continue
        printable = sum(ch.isprintable() or ch in "\n\t" for ch in text) / len(text)
        useful = any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" or ch in "@<" for ch in text)
        if printable >= 0.75 and useful:
            return text
    return ""


class WeChat4SqlcipherBackend(ReceiverBackend):
    def __init__(self, info: WeChatProcessInfo) -> None:
        self.info = info
        self.wxid, self._master_key = extract_process_identity(info)
        accounts = account_directories(info.data_root)
        self.account_dir = match_account(accounts, self.wxid, self._account_key_matches)
        self.account_id = self.wxid
        self._temp = tempfile.TemporaryDirectory(prefix="hermes-wechat-db-")
        self._plain_root = Path(self._temp.name)
        self._snapshot_signatures: dict[str, tuple] = {}
        self._conversation_db: dict[str, Path] = {}
        self._contact_names: dict[str, str] = {}
        self._refresh_metadata()
        probe_paths = [self._snapshot(Path("session/session.db")), self._snapshot(Path("contact/contact.db"))]
        message_paths = self._message_sources()
        if message_paths:
            probe_paths.append(self._snapshot(message_paths[0].relative_to(self.account_dir / "db_storage")))
        probe = probe_sqlite(probe_paths)
        required = {"sessions", "messages", "stable_message_id", "sender_id"}
        if not required <= set(probe.capabilities):
            raise BackendUnavailable(f"Unsupported WeChat DB schema capabilities: {probe.capabilities}")
        self._schema_fingerprint = probe.fingerprint
        self._capabilities = probe.capabilities + ("conversation_id", "is_self", "group_detection")

    def _account_key_matches(self, account: Path) -> bool:
        db = account / "db_storage" / "message" / "message_0.db"
        if not db.is_file():
            return False
        first = db.read_bytes()[:_PAGE_SIZE]
        return _verify_key(db, _derive_key(self._master_key, first))

    def _signature(self, source: Path) -> tuple:
        rows = []
        for path in (source, Path(str(source) + "-wal")):
            try:
                stat = path.stat()
                rows.append((str(path), stat.st_size, stat.st_mtime_ns))
            except OSError:
                rows.append((str(path), 0, 0))
        return tuple(rows)

    def _snapshot(self, relative: Path) -> Path:
        source = self.account_dir / "db_storage" / relative
        if not source.is_file():
            raise BackendUnavailable(f"Required WeChat DB is missing: {relative}")
        key_name = str(relative).replace("\\", "_").replace("/", "_")
        destination = self._plain_root / key_name
        signature = self._signature(source)
        if self._snapshot_signatures.get(key_name) != signature or not destination.is_file():
            first = source.read_bytes()[:_PAGE_SIZE]
            key = _derive_key(self._master_key, first)
            if not _verify_key(source, key):
                raise BackendUnavailable(f"WeChat DB key verification failed: {relative}")
            _decrypt_database(source, destination, key)
            self._snapshot_signatures[key_name] = signature
        return destination

    def _message_sources(self) -> list[Path]:
        folder = self.account_dir / "db_storage" / "message"
        return sorted(path for path in folder.glob("message_*.db") if path.stem.split("_")[-1].isdigit())

    def _connect(self, relative: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(self._snapshot(relative))
        connection.row_factory = sqlite3.Row
        return connection

    def _refresh_metadata(self) -> None:
        connection = None
        try:
            connection = self._connect(Path("contact/contact.db"))
            names: dict[str, str] = {}
            for row in connection.execute("select username, remark, nick_name, alias from contact"):
                username = _decode(row["username"])
                display = _decode(row["remark"]) or _decode(row["nick_name"]) or _decode(row["alias"]) or username
                if username:
                    names[username] = display
            self._contact_names = names
        except Exception:
            self._contact_names = {}
        finally:
            if connection is not None:
                connection.close()

    def status(self) -> BackendStatus:
        return BackendStatus(
            backend="wechat4-sqlcipher-capability",
            account_id=self.account_id,
            data_root=str(self.info.data_root),
            schema_fingerprint=self._schema_fingerprint,
            capabilities=tuple(sorted(set(self._capabilities))),
        )

    def _sessions(self) -> list[dict]:
        self._refresh_metadata()
        connection = self._connect(Path("session/session.db"))
        try:
            return [dict(row) for row in connection.execute(
                "select username, unread_count, last_timestamp, last_msg_locald_id, last_msg_sender, last_sender_display_name from SessionTable"
            )]
        finally:
            connection.close()

    def _table_name(self, conversation_id: str) -> str:
        return "Msg_" + hashlib.md5(conversation_id.encode("utf-8")).hexdigest()

    def _message_connection(self, conversation_id: str) -> tuple[sqlite3.Connection, str] | None:
        table = self._table_name(conversation_id)
        cached = self._conversation_db.get(conversation_id)
        sources = [cached] if cached else []
        sources.extend(path for path in self._message_sources() if path != cached)
        for source in sources:
            if source is None:
                continue
            relative = source.relative_to(self.account_dir / "db_storage")
            connection = self._connect(relative)
            exists = connection.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone()
            if exists:
                self._conversation_db[conversation_id] = source
                return connection, table
            connection.close()
        return None

    def _max_sort(self, conversation_id: str) -> int:
        found = self._message_connection(conversation_id)
        if not found:
            return 0
        connection, table = found
        try:
            row = connection.execute(f'select max(sort_seq) from "{table}"').fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            connection.close()

    def _sender_map(self, connection: sqlite3.Connection) -> dict[int, str]:
        try:
            return {int(row[0]): _decode(row[1]) for row in connection.execute("select rowid, user_name from Name2Id")}
        except sqlite3.DatabaseError:
            return {}

    def _rows(self, conversation_id: str, *, after: int | None = None, latest: int | None = None) -> list[dict]:
        found = self._message_connection(conversation_id)
        if not found:
            return []
        connection, table = found
        try:
            senders = self._sender_map(connection)
            select = (
                f'select local_id, server_id, local_type, sort_seq, real_sender_id, create_time, status, '
                f'message_content, source from "{table}"'
            )
            params: tuple = ()
            if after is not None:
                select += " where sort_seq > ? order by sort_seq asc"
                params = (int(after),)
            elif latest is not None:
                select += " order by sort_seq desc limit ?"
                params = (max(1, int(latest)),)
            else:
                select += " order by sort_seq asc"
            rows = [dict(row) for row in connection.execute(select, params)]
            if latest is not None:
                rows.reverse()
            for row in rows:
                row["sender_id"] = senders.get(int(row.get("real_sender_id") or 0), "")
            return rows
        finally:
            connection.close()

    def conversation_name(self, conversation_id: str) -> str:
        if conversation_id in self._contact_names:
            return self._contact_names[conversation_id]
        connection = None
        try:
            connection = self._connect(Path("session/session.db"))
            row = connection.execute("select session_title from SessionNoContactInfoTable where username=?", (conversation_id,)).fetchone()
            if row and _decode(row[0]):
                return _decode(row[0])
        except sqlite3.DatabaseError:
            pass
        finally:
            if connection is not None:
                connection.close()
        return conversation_id

    @staticmethod
    def _message_type(local_type: int) -> str:
        return {1: "text", 3: "image", 34: "voice", 43: "video", 47: "emoji", 49: "app", 10000: "system"}.get(int(local_type or 0), "other")

    def _event(self, conversation_id: str, row: dict, mention_names: Iterable[str]) -> WeChatMessageEvent:
        sender_id = _decode(row.get("sender_id"))
        if not sender_id:
            sender_id = conversation_id
        is_self = sender_id == self.wxid
        content = _container_text(row.get("message_content"))
        source = _container_text(row.get("source"))
        conversation_type = "group" if conversation_id.endswith("@chatroom") else "dm"
        if conversation_type == "group" and sender_id and content.startswith(sender_id + ":\n"):
            content = content[len(sender_id) + 2 :].lstrip()
        mentioned = False
        if conversation_type == "group":
            source_lower = source.lower()
            mentioned = bool(self.wxid and self.wxid.lower() in source_lower and "atuser" in source_lower)
            if not mentioned and "@" in content:
                mentioned = any(str(name or "").strip() and str(name).strip() in content for name in mention_names)
        server_id = int(row.get("server_id") or 0)
        local_id = int(row.get("local_id") or 0)
        sort_seq = int(row.get("sort_seq") or 0)
        message_id = f"{self.account_id}:{server_id}" if server_id else f"{self.account_id}:{conversation_id}:{local_id}:{sort_seq}"
        msg_type = self._message_type(int(row.get("local_type") or 0))
        if not content and msg_type != "text":
            content = f"[{msg_type}]"
        return WeChatMessageEvent(
            account_id=self.account_id,
            conversation_id=conversation_id,
            conversation_name=self.conversation_name(conversation_id),
            conversation_type=conversation_type,
            sender_id=sender_id,
            sender_name=self._contact_names.get(sender_id, sender_id),
            message_id=message_id,
            timestamp=WeChatMessageEvent.timestamp_from_epoch(row.get("create_time")),
            content=content,
            is_self=is_self,
            mentioned_me=mentioned,
            message_type=msg_type,
            sort_seq=sort_seq,
            raw={"local_id": local_id, "server_id": server_id, "status": row.get("status")},
        )

    def bootstrap_cursors(self) -> dict[str, int]:
        return {str(row.get("username") or ""): self._max_sort(str(row.get("username") or "")) for row in self._sessions() if row.get("username")}

    def unread_events(self, cursors: dict[str, int], mention_names: Iterable[str] = ()) -> tuple[list[WeChatMessageEvent], dict[str, int]]:
        events: list[WeChatMessageEvent] = []
        seed: dict[str, int] = {}
        for session in self._sessions():
            conversation_id = _decode(session.get("username"))
            if not conversation_id:
                continue
            if conversation_id in cursors:
                rows = self._rows(conversation_id, after=int(cursors[conversation_id]))
                events.extend(self._event(conversation_id, row, mention_names) for row in rows)
                continue
            unread = max(0, int(session.get("unread_count") or 0))
            if unread:
                rows = self._rows(conversation_id, latest=min(unread, 200))
                events.extend(self._event(conversation_id, row, mention_names) for row in rows)
            else:
                seed[conversation_id] = self._max_sort(conversation_id)
        events.sort(key=lambda event: (event.timestamp, event.sort_seq, event.message_id))
        return events, seed

    def new_events(self, cursors: dict[str, int], mention_names: Iterable[str] = ()) -> tuple[list[WeChatMessageEvent], dict[str, int]]:
        return self.unread_events(cursors, mention_names)

    def verify_outbound(self, conversation_id: str, content: str, *, after_epoch: float, timeout: float = 8.0) -> bool:
        expected = str(content or "").strip()
        deadline = time.monotonic() + max(0.5, float(timeout))
        while time.monotonic() < deadline:
            rows = self._rows(conversation_id, latest=12)
            for row in reversed(rows):
                sender_id = _decode(row.get("sender_id"))
                created = float(row.get("create_time") or 0)
                if sender_id == self.wxid and created + 2 >= float(after_epoch) and _container_text(row.get("message_content")).strip() == expected:
                    return True
            time.sleep(0.25)
        return False

    def close(self) -> None:
        self._conversation_db = {}
        self._snapshot_signatures = {}
        self._master_key = bytes(len(self._master_key))
        try:
            self._temp.cleanup()
        except PermissionError:
            pass
