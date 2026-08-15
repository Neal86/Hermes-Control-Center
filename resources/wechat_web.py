from __future__ import annotations

import hashlib
import json
import urllib.request
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


class WeChatWebAdapter:
    """Stable WeChat Web Adapter implemented on top of direct Chrome CDP.

    Architecture is intentionally two-layered:
      Hermes tools -> WeChatWebAdapter -> CDP/DOM -> WeChat Web.

    Hermes never receives raw selectors or generic CDP primitives. All WeChat
    page-specific DOM details live inside this adapter so a future WeChat Web UI
    change only requires adapter maintenance. Non-WeChat websites remain routed
    to Hermes native browser/computer-use capabilities.
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

    @staticmethod
    def _is_wechat_url(url: str) -> bool:
        try:
            host = (urlparse(str(url or "")).hostname or "").lower()
        except Exception:
            host = ""
        return host == "wx.qq.com" or host.endswith(".wx.qq.com") or host == "web.wechat.com"

    def _target(self) -> dict[str, Any]:
        port = int(self._resource()["debug_port"])
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/json",
            headers={"Accept": "application/json", "User-Agent": "Hermes-Control-Center/WeChatWebAdapter"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310 - loopback only
            rows = json.loads(response.read(4 * 1024 * 1024).decode("utf-8", "replace"))
        for row in rows if isinstance(rows, list) else []:
            if row.get("type") in {"page", "webview"} and self._is_wechat_url(str(row.get("url") or "")):
                if row.get("webSocketDebuggerUrl"):
                    return row
        raise RuntimeError("bound browser has no open WeChat Web tab")

    def _command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            import websocket
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("websocket-client is not installed in Hermes Control Center") from exc

        target = self._target()
        socket = websocket.create_connection(str(target["webSocketDebuggerUrl"]), timeout=5)
        try:
            socket.send(json.dumps({"id": 1, "method": method, "params": params or {}}, ensure_ascii=False))
            while True:
                raw = socket.recv()
                message = json.loads(raw)
                if message.get("id") != 1:
                    continue
                if message.get("error"):
                    raise RuntimeError(str(message["error"]))
                return dict(message.get("result") or {})
        finally:
            socket.close()

    def _eval(self, expression: str) -> Any:
        result = self._command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
        remote = result.get("result") or {}
        if remote.get("exceptionDetails"):
            raise RuntimeError(str(remote["exceptionDetails"]))
        if remote.get("subtype") == "error":
            raise RuntimeError(str(remote.get("description") or "WeChat Web DOM evaluation failed"))
        return remote.get("value")

    @staticmethod
    def _chat_rows_expression() -> str:
        return r"""(() => {
  const roots = [
    ...document.querySelectorAll('.chat_list .chat_item'),
    ...document.querySelectorAll('[ng-repeat*="chatContact"], [ng-repeat*="chatList"]'),
    ...document.querySelectorAll('[data-conversation-id], [data-user-name]')
  ];
  const seen = new Set(); const out = [];
  for (const el of roots) {
    const nameEl = el.querySelector('.nickname, .nickname_text, .chat_item_name, .title_name, [class*="nickname"]');
    const name = (nameEl?.innerText || nameEl?.textContent || '').trim();
    if (!name) continue;
    const rawId = el.getAttribute('data-conversation-id') || el.getAttribute('data-user-name') || el.getAttribute('data-username') || el.getAttribute('data-id') || '';
    const key = rawId || name; if (seen.has(key)) continue; seen.add(key);
    const unreadEl = el.querySelector('.web_wechat_reddot, .web_wechat_reddot_middle, [class*="unread"], [class*="reddot"]');
    const text = (unreadEl?.innerText || unreadEl?.textContent || '').trim();
    let unreadCount = 0; if (text && /^\d+$/.test(text)) unreadCount = Number(text); else if (unreadEl) unreadCount = 1;
    out.push({raw_id:rawId,name,unread:Boolean(unreadEl),unread_count:unreadCount});
  }
  return out;
})()"""

    def status(self) -> dict[str, Any]:
        target = self._target()
        logged_in = bool(self._eval("Boolean(document.querySelector('.chat_list, #chatArea, .chat_bd'))"))
        title = self._eval("document.title") or str(target.get("title") or "")
        return {
            "source": "wechat_web",
            "adapter": "wechat_web_adapter",
            "driver": "cdp_dom",
            "agent": self.agent,
            "url": str(target.get("url") or ""),
            "title": str(title or ""),
            "logged_in": logged_in,
        }

    def list_chats(self, limit: int = 50) -> list[WebChat]:
        limit = max(1, min(int(limit), 200))
        rows = self._eval(self._chat_rows_expression()) or []
        result: list[WebChat] = []
        for row in rows[:limit]:
            name = str(row.get("name") or "").strip()
            raw_id = str(row.get("raw_id") or "").strip()
            if not name:
                continue
            result.append(
                WebChat(
                    conversation_id=raw_id or f"wechat-web:{_stable_id(name)}",
                    conversation_name=name,
                    unread=bool(row.get("unread")),
                    unread_count=int(row.get("unread_count") or 0),
                )
            )
        return result

    def unread_chats(self, limit: int = 50) -> list[WebChat]:
        return [row for row in self.list_chats(200) if row.unread][: max(1, min(int(limit), 200))]

    def _resolve_chat(self, wanted: str) -> dict[str, str]:
        wanted = str(wanted or "").strip()
        if not wanted:
            raise ValueError("chat is required")
        rows = self._eval(self._chat_rows_expression()) or []
        for row in rows:
            name = str(row.get("name") or "").strip()
            raw = str(row.get("raw_id") or "").strip()
            cid = raw or f"wechat-web:{_stable_id(name)}"
            if wanted in {name, raw, cid}:
                return {"conversation_id": cid, "conversation_name": name, "raw_id": raw}
        raise RuntimeError(f"WeChat conversation not found: {wanted}")

    def _open_chat(self, chat: str) -> dict[str, str]:
        meta = self._resolve_chat(chat)
        payload = json.dumps(meta, ensure_ascii=False)
        expression = f"""(() => {{
  const m={payload};
  const roots=[...document.querySelectorAll('.chat_list .chat_item,[ng-repeat*=\"chatContact\"],[ng-repeat*=\"chatList\"],[data-conversation-id],[data-user-name]')];
  let target=null;
  if(m.raw_id) target=roots.find(el=>[el.getAttribute('data-conversation-id'),el.getAttribute('data-user-name'),el.getAttribute('data-username'),el.getAttribute('data-id')].includes(m.raw_id));
  if(!target) target=roots.find(el=>{{ const n=el.querySelector('.nickname,.nickname_text,.chat_item_name,.title_name,[class*=\"nickname\"]'); return ((n?.innerText||n?.textContent||'').trim()===m.conversation_name); }});
  if(!target) return false; target.scrollIntoView({{block:'center'}}); target.click(); return true;
}})()"""
        if not self._eval(expression):
            raise RuntimeError(f"WeChat conversation could not be opened: {meta['conversation_name']}")
        return meta

    def get_messages(self, chat: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        meta = self._open_chat(chat)
        rows = self._eval(r"""(() => {
  const nodes=[...document.querySelectorAll('#chatArea .message,.chat_bd .message,[ng-repeat*="message"]')];
  return nodes.map((el,index)=>{
    const textEl=el.querySelector('.plain pre,.content .plain,.js_message_plain,[class*="plain"]');
    const senderEl=el.querySelector('.nickname,.avatar + * [class*="name"],[class*="sender"]');
    const text=(textEl?.innerText||textEl?.textContent||'').trim();
    const sender=(senderEl?.innerText||senderEl?.textContent||'').trim();
    const cls=String(el.className||''); const direction=/me|message_me|sent|outgoing/i.test(cls)?'outgoing':'incoming';
    const rawId=el.getAttribute('data-message-id')||el.getAttribute('data-msgid')||el.getAttribute('data-id')||el.id||'';
    return {raw_id:rawId,text,sender,direction,index};
  }).filter(x=>x.text);
})()""") or []
        result: list[dict[str, Any]] = []
        for row in rows[-limit:]:
            raw_id = str(row.get("raw_id") or "").strip()
            text = str(row.get("text") or "")
            result.append({
                "source": "wechat_web",
                "conversation_id": meta["conversation_id"],
                "conversation_name": meta["conversation_name"],
                "message_id": raw_id or f"wechat-web-msg:{_stable_id(meta['conversation_id'], str(row.get('index')), text)}",
                "sender": str(row.get("sender") or ""),
                "direction": str(row.get("direction") or "incoming"),
                "text": text,
            })
        return result

    def send_message(self, chat: str, text: str, *, dry_run: bool = False) -> dict[str, Any]:
        text = str(text or "")
        if not text:
            raise ValueError("text is required")
        meta = self._open_chat(chat)
        if dry_run:
            return {"ok": True, "dry_run": True, **meta, "text": text, "source": "wechat_web", "adapter": "wechat_web_adapter", "driver": "cdp_dom"}
        payload = json.dumps(text, ensure_ascii=False)
        ok = self._eval(f"""(() => {{
  const editor=document.querySelector('#editArea')||document.querySelector('[contenteditable=\"true\"][ng-model*=\"editArea\"]')||document.querySelector('.edit_area [contenteditable=\"true\"]')||document.querySelector('[contenteditable=\"true\"]');
  if(!editor) return false; editor.focus();
  const text={payload};
  if('value' in editor) {{ editor.value=text; editor.dispatchEvent(new Event('input',{{bubbles:true}})); }}
  else {{ editor.innerHTML=''; document.execCommand('insertText',false,text); editor.dispatchEvent(new InputEvent('input',{{bubbles:true,inputType:'insertText',data:text}})); }}
  editor.dispatchEvent(new KeyboardEvent('keydown',{{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}}));
  editor.dispatchEvent(new KeyboardEvent('keyup',{{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}}));
  return true;
}})()""")
        if not ok:
            raise RuntimeError("WeChat Web message editor was not found")
        return {"ok": True, "dry_run": False, **meta, "text": text, "source": "wechat_web", "adapter": "wechat_web_adapter", "driver": "cdp_dom"}


# Backward-compatible alias for previously installed builds.
BoundWeChatWeb = WeChatWebAdapter
