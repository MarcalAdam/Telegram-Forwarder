import os
import json
from dotenv import load_dotenv

load_dotenv()

# === Telegram ===
TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION_NAME = os.getenv("TG_SESSION_NAME", "sessao")

# SOURCE_CHAT (único) ou SOURCE_CHATS (lista separada por vírgula, ex: "-1001,@canal")
_raw_source = os.getenv("SOURCE_CHAT", "").strip()
if _raw_source:
    if _raw_source.lstrip("-").isdigit():
        SOURCE_CHAT = int(_raw_source)
    else:
        SOURCE_CHAT = _raw_source.lstrip("@")
else:
    SOURCE_CHAT = None

# Lista bruta; os helpers normalizam (ids -> int, @user -> str sem @)
SOURCE_CHATS = os.getenv("SOURCE_CHATS")  # ex: "-1001,@canal"

# --- Tópicos: TOPIC_ID (único) OU TOPIC_MAP (JSON) ---
# Exemplo TOPIC_MAP no .env: {"-1002427024288":[4,14,31]}
_raw_topic_map = os.getenv("TOPIC_MAP", "").strip()
TOPIC_MAP = None
if _raw_topic_map:
    try:
        TOPIC_MAP = json.loads(_raw_topic_map)
    except Exception:
        TOPIC_MAP = None  # JSON inválido -> ignora e usa TOPIC_ID

# TOPIC_ID só faz sentido se NÃO houver TOPIC_MAP
_raw_tid = os.getenv("TOPIC_ID", "").strip()
if TOPIC_MAP:
    TOPIC_ID = None
else:
    if _raw_tid and _raw_tid.lstrip("-").isdigit():
        TOPIC_ID = int(_raw_tid)
    else:
        TOPIC_ID = None

# --- Destinos ---
# Fallback global (id numérico, @username ou "me")
_raw_target = os.getenv("TARGET_CHAT", "me").strip()
if _raw_target.lstrip("-").isdigit():
    TARGET_CHAT = int(_raw_target)
else:
    TARGET_CHAT = _raw_target.lstrip("@")  # "me" ou username sem @

# TARGET_MAP (JSON) com regras por chat e opcionalmente por tópico
# Formatos aceitos (chave -> destino):
#  "-1002427024288": "@destino"                 (por chat)
#  "-1002427024288|4": "-4986598952"            (por chat + tópico)
#  "@canal": "@destino"                         (por username do chat)
_raw_tmap = os.getenv("TARGET_MAP", "").strip()
TARGET_MAP = {}
if _raw_tmap:
    try:
        raw = json.loads(_raw_tmap)
        for k, v in raw.items():
            key = str(k).strip()
            # normaliza destino: int se numérico, senão username sem @
            v_norm = str(v).strip()
            v_norm = int(v_norm) if v_norm.lstrip("-").isdigit() else v_norm.lstrip("@")

            if "|" in key:
                chat_key, topic_key = key.split("|", 1)
                ck = int(chat_key) if chat_key.lstrip("-").isdigit() else chat_key.lstrip("@").lower()
                try:
                    tk = int(topic_key)
                except Exception:
                    continue
                TARGET_MAP[(ck, tk)] = v_norm
            else:
                ck = int(key) if key.lstrip("-").isdigit() else key.lstrip("@").lower()
                TARGET_MAP[(ck, None)] = v_norm
    except Exception:
        TARGET_MAP = {}

# NOTIFY_ONLY: lista de chaves ("chat" ou "chat|topic") para apenas notificar
# Exemplos válidos no .env:
#  NOTIFY_ONLY=["-1002427024288|4","@canal|10"]
#  NOTIFY_ONLY="-1002427024288|4,@canal|10" (string separada por vírgulas)
_raw_notify = os.getenv("NOTIFY_ONLY", "").strip()
NOTIFY_ONLY = set()
if _raw_notify:
    try:
        parsed = json.loads(_raw_notify)
        if isinstance(parsed, dict):
            keys = list(parsed.keys())
        elif isinstance(parsed, list):
            keys = [str(x) for x in parsed]
        else:
            keys = []
    except Exception:
        # tenta como string separada por vírgulas
        keys = [k.strip() for k in _raw_notify.split(",") if k.strip()]

    for key in keys:
        k = str(key)
        if "|" in k:
            chat_key, topic_key = k.split("|", 1)
            ck = int(chat_key) if chat_key.lstrip("-").isdigit() else chat_key.lstrip("@").lower()
            try:
                tk = int(topic_key)
            except Exception:
                continue
            NOTIFY_ONLY.add((ck, tk))
        else:
            ck = int(k) if k.lstrip("-").isdigit() else k.lstrip("@").lower()
            NOTIFY_ONLY.add((ck, None))

# === Gemini ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# === Trading / Bybit (stub) ===
SYMBOL_SUFFIX = os.getenv("SYMBOL_SUFFIX", "USDT")
PRICE_PRECISION = int(os.getenv("PRICE_PRECISION", "2"))
QTY_PRECISION = int(os.getenv("QTY_PRECISION", "4"))
DEFAULT_RISK_PCT = float(os.getenv("DEFAULT_RISK_PCT", "0.01"))
DEFAULT_BALANCE_USDT = float(os.getenv("DEFAULT_BALANCE_USDT", "1000"))

# Perfil de TP
TP_PROFILE = os.getenv("TP_PROFILE", "auto")
TP_AUTO_THRESHOLD_PCT = float(os.getenv("TP_AUTO_THRESHOLD_PCT", "1.2"))
TP_KEYWORD_SCALP = os.getenv("TP_KEYWORD_SCALP", "scalp").lower()
TP_KEYWORD_SWING = os.getenv("TP_KEYWORD_SWING", "swing").lower()
