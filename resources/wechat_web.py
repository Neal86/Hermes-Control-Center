from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .bindings import ResourceBindings


@dataclass(slots=True)
class WebChat:
    conversation_id: str
    conversation_name: str
    unread: bool
    unread_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "conversation_name": self.conversation_name,
            "unread": self.unread,
            "unread_count": self.unread_count,
            "source": "wechat_web",
        }


def _stable_id(*parts: str) -> str:
    raw = "\0".join(str(p or "").strip() for p in parts)
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:24]


class BoundWeChatWeb:
    """Playwright-over-CDP adapter for the Agent's bound Chromium browser.

    The browser lifecycle and profile are owned by Control Center. This adapter
    only attaches to the already-running CDP endpoint and never launches a new
    browser itself.
    """

    def __init__(self, agent: str) -> None:
        self.agent = str(agent or "").strip().lower()
        if not self.agent:
            raise ValueError("agent is required")

    def _resource(self) -> dict[str, Any]:
        row = ResourceBindings().require(self.agent, "browser", ready=True)
        port = int(row.get("debug_port") or 0)
        if not port:
            raise RuntimeError("bound browser has no usable CDP port")
        return row

    def _with_page(self, fn):
        row = self._resource()
        port = int(row["debug_port"])
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - runtime dependency check
            raise RuntimeError("Playwright is not installed in the Hermes Control Center runtime") from exc

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            try:
                contexts = browser.contexts
                if not contexts:
                    raise RuntimeError("CDP browser has no browser context")
                pages = [page for context in contexts for page in context.pages]
                page = next((p for p in pages if self._is_wechat_url(p.url)), None)
                if page is None:
                    raise RuntimeError("bound browser has no open WeChat Web tab")
                page.bring_to_front()
                return fn(page)
            finally:
                browser.close()

    @staticmethod
    def _is_wechat_url(url: str) -> bool:
        try:
            host = (urlparse(str(url or "")).hostname or "").lower()
        except Exception:
            host = ""
        return host == "wx.qq.com" or host.endswith(".wx.qq.com") or host == "web.wechat.com"

    @staticmethod
    def _chat_rows_script() -> str:
        return r"""
() => {
  const roots = [
    ...document.querySelectorAll('.chat_list .chat_item'),
    ...document.querySelectorAll('[ng-repeat*="chatContact"], [ng-repeat*="chatList"]'),
    ...document.querySelectorAll('[data-conversation-id], [data-user-name]')
  ];
  const seen = new Set();
  const out = [];
  for (const el of roots) {
    const nameEl = el.querySelector('.nickname, .nickname_text, .chat_item_name, .title_name, [class*="nickname"]');
    const name = (nameEl?.innerText || nameEl?.textContent || '').trim();
    if (!name) continue;
    const rawId = el.getAttribute('data-conversation-id') || el.getAttribute('data-user-name') ||
                  el.getAttribute('data-username') || el.getAttribute('data-id') || '';
    const key = rawId || name;
    if (seen.has(key)) continue;
    seen.add(key);
    const unreadEl = el.querySelector('.web_wechat_reddot, .web_wechat_reddot_middle, [class*="unread"], [class*="reddot"]');
    let unreadCount = 0;
    const text = (unreadEl?.innerText || unreadEl?.textContent || '').trim();
    if (text && /^\d+$/.test(text)) unreadCount = Number(text);
    else if (unreadEl) unreadCount = 1;
    out.push({
      raw_id: rawId,
      name,
      unread: Boolean(unreadEl),
      unread_count: unreadCount,
    });
  }
  return out;
}
"""

    def status(self) -> dict[str, Any]:
        def load(page):
            return {
                "source": "wechat_web",
                "agent": self.agent,
                "url": page.url,
                "title": page.title(),
                "logged_in": bool(page.locator('.chat_list, #chatArea, .chat_bd').count()),
            }
        return self._with_page(load)

    def list_chats(self, limit: int = 50) -> list[WebChat]:
        limit = max(1, min(int(limit), 200))

        def load(page):
            rows = page.evaluate(self._chat_rows_script()) or []
            result: list[WebChat] = []
            for row in rows[:limit]:
                name = str(row.get("name") or "").strip()
                raw_id = str(row.get("raw_id") or "").strip()
                if not name:
                    continue
                conversation_id = raw_id or f"wechat-web:{_stable_id(name)}"
                result.append(
                    WebChat(
                        conversation_id=conversation_id,
                        conversation_name=name,
                        unread=bool(row.get("unread")),
                        unread_count=int(row.get("unread_count") or 0),
                    )
                )
            return result

        return self._with_page(load)

    def unread_chats(self, limit: int = 50) -> list[WebChat]:
        return [row for row in self.list_chats(200) if row.unread][: max(1, min(int(limit), 200))]

    def _open_chat(self, page, chat: str) -> dict[str, Any]:
        wanted = str(chat or "").strip()
        if not wanted:
            raise ValueError("chat is required")
        rows = page.evaluate(self._chat_rows_script()) or []
        target_name = ""
        target_raw = ""
        for row in rows:
            name = str(row.get("name") or "").strip()
            raw = str(row.get("raw_id") or "").strip()
            cid = raw or f"wechat-web:{_stable_id(name)}"
            if wanted in {name, raw, cid}:
                target_name, target_raw = name, raw
                break
        if not target_name:
            raise RuntimeError(f"WeChat conversation not found: {wanted}")

        selectors = []
        if target_raw:
            escaped = target_raw.replace('\\', '\\\\').replace('"', '\\"')
            selectors.extend([
                f'[data-conversation-id="{escaped}"]',
                f'[data-user-name="{escaped}"]',
                f'[data-username="{escaped}"]',
            ])
        for selector in selectors:
            loc = page.locator(selector)
            if loc.count():
                loc.first.click()
                return {"conversation_id": target_raw or f"wechat-web:{_stable_id(target_name)}", "conversation_name": target_name}

        candidates = page.locator('.chat_list .chat_item, [ng-repeat*="chatContact"], [ng-repeat*="chatList"]')
        for i in range(min(candidates.count(), 500)):
            el = candidates.nth(i)
            try:
                text = (el.inner_text(timeout=500) or "").strip()
            except Exception:
                continue
            if target_name in text:
                el.click()
                return {"conversation_id": target_raw or f"wechat-web:{_stable_id(target_name)}", "conversation_name": target_name}
        raise RuntimeError(f"WeChat conversation could not be opened: {target_name}")

    def get_messages(self, chat: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))

        def load(page):
            meta = self._open_chat(page, chat)
            page.wait_for_timeout(250)
            rows = page.evaluate(r"""
() => {
  const nodes = [
    ...document.querySelectorAll('#chatArea .message'),
    ...document.querySelectorAll('.chat_bd .message'),
    ...document.querySelectorAll('[ng-repeat*="message"]')
  ];
  return nodes.map((el, index) => {
    const textEl = el.querySelector('.plain pre, .content .plain, .js_message_plain, [class*="plain"]');
    const senderEl = el.querySelector('.nickname, .avatar + * [class*="name"], [class*="sender"]');
    const text = (textEl?.innerText || textEl?.textContent || '').trim();
    const sender = (senderEl?.innerText || senderEl?.textContent || '').trim();
    const cls = String(el.className || '');
    const direction = /me|message_me|sent|outgoing/i.test(cls) ? 'outgoing' : 'incoming';
    const rawId = el.getAttribute('data-message-id') || el.getAttribute('data-msgid') ||
                  el.getAttribute('data-id') || el.id || '';
    return {raw_id: rawId, text, sender, direction, index};
  }).filter(x => x.text);
}
""") or []
            rows = rows[-limit:]
            result = []
            for row in rows:
                raw_id = str(row.get("raw_id") or "").strip()
                text = str(row.get("text") or "")
                message_id = raw_id or f"wechat-web-msg:{_stable_id(meta['conversation_id'], str(row.get('index')), text)}"
                result.append({
                    "source": "wechat_web",
                    "conversation_id": meta["conversation_id"],
                    "conversation_name": meta["conversation_name"],
                    "message_id": message_id,
                    "sender": str(row.get("sender") or ""),
                    "direction": str(row.get("direction") or "incoming"),
                    "text": text,
                })
            return result

        return self._with_page(load)

    def send_message(self, chat: str, text: str, *, dry_run: bool = False) -> dict[str, Any]:
        text = str(text or "")
        if not text:
            raise ValueError("text is required")

        def send(page):
            meta = self._open_chat(page, chat)
            if dry_run:
                return {"ok": True, "dry_run": True, **meta, "text": text, "source": "wechat_web"}
            editor = None
            for selector in ('#editArea', '[contenteditable="true"][ng-model*="editArea"]', '.edit_area [contenteditable="true"]', '[contenteditable="true"]'):
                loc = page.locator(selector)
                if loc.count():
                    editor = loc.last
                    break
            if editor is None:
                raise RuntimeError("WeChat Web message editor was not found")
            editor.click()
            editor.fill(text)
            editor.press("Enter")
            page.wait_for_timeout(250)
            return {"ok": True, "dry_run": False, **meta, "text": text, "source": "wechat_web"}

        return self._with_page(send)
