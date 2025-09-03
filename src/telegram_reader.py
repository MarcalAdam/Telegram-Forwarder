import asyncio
import logging
import sys
import getpass
import os
from pathlib import Path
from typing import Dict, Tuple, Optional, Set

from helpers import normalize_sources
from telethon import TelegramClient, events
from telethon.errors import (
    PhoneNumberInvalidError, PhoneCodeInvalidError, PhoneCodeExpiredError,
    SessionPasswordNeededError, FloodWaitError,
)
from telethon.tl.types import Channel
from telethon.tl.functions.channels import GetForumTopicsRequest

import config as config

log = logging.getLogger("tg")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# --- Cliente principal ---
# Garante que a sessão fique sempre na raiz do projeto (../), independente do cwd
_BASE_DIR = Path(__file__).resolve().parent.parent
_SESSION_NAME = str(_BASE_DIR / config.TG_SESSION_NAME)
client = TelegramClient(_SESSION_NAME, config.TG_API_ID, config.TG_API_HASH)


# =============================================================================
# Autenticação
# =============================================================================
async def ensure_login():
    await client.connect()
    if await client.is_user_authorized():
        try:
            me = await client.get_me()
            uname = getattr(me, "username", None)
            phone = getattr(me, "phone", None)
            phone_disp = f"+{phone}" if phone and not str(phone).startswith("+") else (phone or "?")
            phone_mask = phone_disp[:-4] + "****" if phone_disp and len(phone_disp) > 6 else phone_disp
            user_str = f"@{uname}" if uname else (getattr(me, "first_name", "Usuário") or "Usuário")
            log.info(f"Sessão já autorizada ✔ Conectado como {user_str} ({phone_mask})")
        except Exception:
            log.info("Sessão já autorizada ✔")
        return

    # Telefone
    tries = 0
    while tries < 3:
        phone = input("📱 Telefone (+5521...): ").strip()
        try:
            await client.send_code_request(phone)
        except PhoneNumberInvalidError:
            log.error("Telefone inválido.")
            tries += 1
            continue
        except FloodWaitError as e:
            log.error(f"Flood wait: aguarde {e.seconds}s.")
            raise
        break
    else:
        raise RuntimeError("Falhas ao informar telefone.")

    # Código / 2FA
    tries = 0
    while tries < 3:
        code = input("🔐 Código Telegram/SMS: ").strip()
        try:
            await client.sign_in(phone=phone, code=code)
            log.info("Login concluído ✔")
            return
        except PhoneCodeInvalidError:
            log.error("Código inválido.")
            tries += 1
        except PhoneCodeExpiredError:
            log.error("Código expirado.")
            tries += 1
        except SessionPasswordNeededError:
            for _ in range(3):
                pwd = getpass.getpass("🔒 Senha 2FA: ")
                try:
                    await client.sign_in(password=pwd)
                    log.info("Login 2FA concluído ✔")
                    return
                except Exception:
                    log.error("Senha 2FA incorreta.")
            raise RuntimeError("2FA falhou.")
    raise RuntimeError("Falhas ao informar o código.")


# =============================================================================
# Fast topic mapping (pré-warm)
#   - Por chat: topic_id -> top_msg_id  e  top_msg_id -> (topic_id, title)
#   - ALLOWED_TOP_MSG_IDS: set para checagem instantânea
# =============================================================================
class FastTopicMap:
    def __init__(self):
        # chaves do chat: podem ser id (int) ou username (str)
        self.topic_to_top: Dict[int | str, Dict[int, int]] = {}          # topic_id -> top_msg_id
        self.top_to_topic: Dict[int | str, Dict[int, Tuple[int, str]]] = {}  # top_msg_id -> (topic_id, title)
        self.allowed_top: Dict[int | str, Set[int]] = {}                 # set de top_msg_id permitidos

    def _chat_key(self, chat_obj):
        return getattr(chat_obj, "id", None) or getattr(chat_obj, "username", None)

    async def preload_for_chat(self, chat_obj):
        """Carrega todas as páginas de tópicos (até ~1000) e constrói os mapas."""
        if not (isinstance(chat_obj, Channel) and bool(getattr(chat_obj, "forum", False))):
            return
        chat_key = self._chat_key(chat_obj)

        topic_to_top: Dict[int, int] = {}
        top_to_topic: Dict[int, Tuple[int, str]] = {}

        offset_topic = 0
        total = 0
        for _ in range(5):  # 5 * 200 = 1000 tópicos
            res = await client(GetForumTopicsRequest(
                channel=chat_obj,
                offset_date=None,
                offset_id=0,
                offset_topic=offset_topic,
                limit=200
            ))
            topics = res.topics or []
            if not topics:
                break
            for t in topics:
                if getattr(t, "top_message", None) is None:
                    continue
                tid = int(t.id)
                top = int(t.top_message)
                title = t.title or f"topic#{tid}"
                topic_to_top[tid] = top
                top_to_topic[top] = (tid, title)
                total += 1
            if getattr(res, "count", None) and total >= int(res.count):
                break
            offset_topic = topics[-1].id if topics else 0

        self.topic_to_top[chat_key] = topic_to_top
        self.top_to_topic[chat_key] = top_to_topic
        log.info(f"[topics-fast] pré-carregado chat={chat_key} itens={len(top_to_topic)}")

        # constrói allowed_top para esse chat com base no TOPIC_MAP (se houver)
        allowed_set: Set[int] = set()
        tm = getattr(config, "TOPIC_MAP", None)
        if tm:
            # TOPIC_MAP pode ter chave como int ou str
            for k in (chat_key, str(chat_key)):
                topics_whitelist = tm.get(k) if isinstance(tm, dict) else None
                if topics_whitelist:
                    for topic_id in topics_whitelist:
                        try:
                            topic_id = int(topic_id)
                        except Exception:
                            continue
                        top_msg_id = topic_to_top.get(topic_id)
                        if top_msg_id:
                            allowed_set.add(top_msg_id)
        self.allowed_top[chat_key] = allowed_set
        if allowed_set:
            log.info(f"[topics-fast] allowed_top para chat={chat_key}: {len(allowed_set)} tópicos")

    async def preload_for_sources(self, sources: Set[int | str]):
        """Pré-carrega mapas para todos os sources configurados (ids e usernames)."""
        for s in sources:
            try:
                # s pode ser int (id) ou str (username sem @)
                entity = await client.get_entity(s)
                await self.preload_for_chat(entity)
            except Exception as e:
                log.error(f"[topics-fast] falha ao pré-carregar {s}: {e}")

    def resolve_from_top(self, chat_obj, top_msg_id: Optional[int]) -> Tuple[Optional[int], Optional[str]]:
        """Resolve (topic_id, title) a partir do top_msg_id usando o cache já carregado (sem I/O)."""
        if not isinstance(top_msg_id, int):
            return None, None
        chat_key = self._chat_key(chat_obj)
        m = self.top_to_topic.get(chat_key) or {}
        info = m.get(top_msg_id)
        return info if info else (None, None)

    def is_top_allowed(self, chat_obj, top_msg_id: Optional[int]) -> bool:
        """Checa instantaneamente se esse top_msg_id está whitelisted (sem I/O)."""
        if not isinstance(top_msg_id, int):
            return False
        chat_key = self._chat_key(chat_obj)
        allowed = self.allowed_top.get(chat_key) or set()
        return top_msg_id in allowed


fastmap = FastTopicMap()


async def extract_top_msg_id(message) -> Optional[int]:
    """
    Extrai o top_msg_id do evento/mensagem com fallbacks.
    (Sem I/O; nada de refetch aqui)
    """
    if message is None:
        return None

    # 1) reply_to.* (mais comum)
    r = getattr(message, "reply_to", None)
    if r is not None:
        v = getattr(r, "top_msg_id", None) or getattr(r, "reply_to_top_id", None)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.lstrip("-").isdigit():
            return int(v)

    # 2) campos diretos (em algumas builds)
    for attr in ("top_msg_id", "reply_to_top_id"):
        v = getattr(message, attr, None)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.lstrip("-").isdigit():
            return int(v)

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

    # 4) raiz do tópico: o id da própria msg == top_msg_id — mas sem garantias aqui.
    #    Para velocidade, não faremos heurística; se necessário, o fastmap já tem os "tops permitidos".
    return None


# =============================================================================
# Listener
# =============================================================================
def start_listening(on_message):
    """
    on_message: callable(texto:str, event) -> None | awaitable

    Roteamento:
      - PRÉ-CARREGA tópicos dos SOURCEs no boot (1x).
      - Só passa ao handler se:
          a) não há TOPIC_MAP (sem restrição), OU
          b) top_msg_id ∈ ALLOWED_TOP_MSG_IDS para o chat.
      - Destino é decidido por TARGET_MAP:
          (chat, topic_id) -> (chat, top_msg_id) -> (chat, None) -> TARGET_CHAT.
      - Injeta no event: _target_chat, _topic_id, _topic_title, _chat_title
    """
    sources = normalize_sources(
        getattr(config, "SOURCE_CHATS", None),
        fallback_source=config.SOURCE_CHAT
    )
    log.info(f"[boot] sources={sources}")

    # pré-carrega mapas para todos os sources (sem bloquear o router)
    async def _prewarm():
        try:
            await ensure_login()  # garante sessão antes de get_entity
            await fastmap.preload_for_sources(sources)
        except Exception as e:
            log.error(f"[prewarm] falha: {e}")

    # dispara prewarm (não bloqueia)
    asyncio.create_task(_prewarm())
    log.info("🔊 Ouvindo novos eventos do Telegram...")

    @client.on(events.NewMessage())
    async def router(event):
        # Descoberta
        if not sources:
            try:
                chat = await event.get_chat()
                title = getattr(chat, "title", None) or getattr(chat, "first_name", "Privado")
                print(f"💡 Chat ID: {event.chat_id} | Nome: {title}")
            except Exception as e:
                log.error(f"Falha ao obter chat: {e}")
            return

        # Match do chat
        try:
            chat_id = event.chat_id
            chat_obj = await event.get_chat()
            chat_username = getattr(chat_obj, "username", None)
            chat_username = chat_username.lstrip("@").lower() if chat_username else None
            match = (chat_id in sources) or (chat_username and chat_username in sources)
            if not match:
                return
        except Exception as e:
            log.error(f"Erro ao checar SOURCE_CHATS: {e}")
            return

        # top_msg_id (sem I/O)
        msg = getattr(event, "message", None)
        top_msg_id = await extract_top_msg_id(msg)

        # Se há TOPIC_MAP, só seguimos se top_msg_id estiver whitelisted (instantâneo)
        tm = getattr(config, "TOPIC_MAP", None)
        if tm:
            # se o prewarm ainda não terminou, pode não ter allowed_top ainda:
            if not fastmap.is_top_allowed(chat_obj, top_msg_id):
                # nada de I/O aqui; simplesmente ignore até que o prewarm acabe
                log.info(f"[router-skip] chat={chat_id} top_msg_id={top_msg_id} não permitido (ainda).")
                return

        # Resolve (topic_id, title) a partir do top_msg_id (sem I/O)
        topic_id, topic_title = fastmap.resolve_from_top(chat_obj, top_msg_id)

        # Resolve TARGET
        target = config.TARGET_CHAT
        try:
            # 1) (chat, topic_id)
            if (chat_id, topic_id) in config.TARGET_MAP:
                target = config.TARGET_MAP[(chat_id, topic_id)]
            elif chat_username and (chat_username, topic_id) in config.TARGET_MAP:
                target = config.TARGET_MAP[(chat_username, topic_id)]
            # 2) (chat, top_msg_id)
            elif (chat_id, top_msg_id) in config.TARGET_MAP:
                target = config.TARGET_MAP[(chat_id, top_msg_id)]
            elif chat_username and (chat_username, top_msg_id) in config.TARGET_MAP:
                target = config.TARGET_MAP[(chat_username, top_msg_id)]
            # 3) (chat, None)
            elif (chat_id, None) in config.TARGET_MAP:
                target = config.TARGET_MAP[(chat_id, None)]
            elif chat_username and (chat_username, None) in config.TARGET_MAP:
                target = config.TARGET_MAP[(chat_username, None)]
            # 4) fallback global
        except Exception as e:
            log.error(f"Erro ao resolver TARGET_MAP: {e}")

        log.info(f"[router] chat={chat_id} user={chat_username} top_msg_id={top_msg_id} topic_id={topic_id} -> target={target}")

        # Injeta dados para o on_message (se você quiser usar)
        setattr(event, "_target_chat", target)
        setattr(event, "_topic_id", topic_id)
        setattr(event, "_topic_title", topic_title)
        setattr(event, "_chat_username", chat_username)
        setattr(event, "_chat_title", getattr(chat_obj, "title", None) or getattr(chat_obj, "first_name", "Privado"))

        # Texto e handler
        text = (event.raw_text or "").strip()
        if not text:
            return
        await on_message(text, event)

    return client


# =============================================================================
# Loop
# =============================================================================
async def run_forever(client):
    print("\n🔌 Telegram ouvindo... Ctrl+C para sair\n")
    try:
        # Garante conexão ativa antes de aguardar
        if not client.is_connected():
            await client.connect()
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n👋 Encerrando sessão...")
        await client.disconnect()
        print("✅ Finalizado.")