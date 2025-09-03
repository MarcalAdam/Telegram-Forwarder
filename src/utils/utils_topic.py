from typing import Tuple, Optional, Dict
from telethon.tl.types import Channel
from telethon.tl.functions.channels import GetForumTopicsRequest

class TopicResolver:
    """
    Mantém cache por chat: { top_msg_id -> (topic_id, title) }.
    Usa paginação e faz refresh quando necessário.
    """
    def __init__(self, client, pages: int = 5, page_size: int = 200):
        self.client = client
        self.pages = pages
        self.page_size = page_size
        self.cache: Dict[int | str, Dict[int, Tuple[int, str]]] = {}  # chat_key -> map

    async def _ensure_cache(self, chat_obj, force: bool = False):
        if not isinstance(chat_obj, Channel) or not getattr(chat_obj, "forum", False):
            return
        chat_key = getattr(chat_obj, "id", None) or getattr(chat_obj, "username", None)
        if not force and chat_key in self.cache and self.cache[chat_key]:
            return

        mapping: Dict[int, Tuple[int, str]] = {}
        offset_topic = 0
        for _ in range(self.pages):  # até pages * page_size tópicos
            res = await self.client(GetForumTopicsRequest(
                channel=chat_obj,
                offset_date=None,
                offset_id=0,
                offset_topic=offset_topic,
                limit=self.page_size
            ))
            topics = res.topics or []
            if not topics:
                break
            for t in topics:
                if getattr(t, "top_message", None) is not None:
                    mapping[int(t.top_message)] = (int(t.id), t.title or f"topic#{t.id}")
            # parar se já cobrimos o count informado
            if getattr(res, "count", None) and len(mapping) >= int(res.count):
                break
            offset_topic = topics[-1].id if topics else 0

        if mapping:
            self.cache[chat_key] = mapping

    async def topmsg_to_topic(self, chat_obj, top_msg_id: Optional[int]) -> Tuple[Optional[int], Optional[str]]:
        if not isinstance(top_msg_id, int):
            return None, None
        chat_key = getattr(chat_obj, "id", None) or getattr(chat_obj, "username", None)
        await self._ensure_cache(chat_obj, force=False)
        m = self.cache.get(chat_key, {})
        info = m.get(top_msg_id)
        if info:
            return info  # (topic_id, title)
        # tenta refresh (pode ser tópico novo)
        await self._ensure_cache(chat_obj, force=True)
        m = self.cache.get(chat_key, {})
        info = m.get(top_msg_id)
        return info if info else (None, None)


async def extract_top_msg_id(message) -> Optional[int]:
    """
    Extrai o top_msg_id do evento/mensagem com vários fallbacks.
    """
    if message is None:
        return None

    # 1) reply_to.* (mais comum)
    r = getattr(message, "reply_to", None)
    if r is not None:
        v = getattr(r, "top_msg_id", None) or getattr(r, "reply_to_top_id", None)
        if isinstance(v, int):
            return v

    # 2) campos diretos (em algumas builds)
    for attr in ("top_msg_id", "reply_to_top_id"):
        v = getattr(message, attr, None)
        if isinstance(v, int):
            return v

    # 3) via to_dict()
    try:
        d = message.to_dict() or {}
        rt = d.get("reply_to", {}) or {}
        v = rt.get("top_msg_id", None) or rt.get("reply_to_top_id", None)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.lstrip("-").isdigit():
            return int(v)
    except Exception:
        pass

    # 4) raiz do tópico: algumas vezes a raiz não traz reply_to;
    #    pode ser necessário mapear pelo próprio id via cache (já coberto em topmsg_to_topic)
    return None
