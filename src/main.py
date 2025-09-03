import asyncio
import logging
from typing import List, Optional, Set

from models import PlanConfig, Order
from parser_signal import (
    parse_signal,           # parser “estrito”
    parse_signal_flexible,  # parser tolerante (fallback)
    is_potential_signal,    # heurística “parece um sinal?”
)
from ai_api import local_validate, gemini_validate
from bybit_client import BybitClient
from telegram_reader import ensure_login, start_listening, run_forever
import config as config
from helpers import build_order_plan, choose_tp_profile, alloc_for_signal

log = logging.getLogger("main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

bybit = BybitClient(testnet=True)

# ---------------- helpers locais ----------------

def _topic_allowed(chat_id: int, topic_id: Optional[int]) -> bool:
    """
    Retorna True se topic_id estiver permitido em TOPIC_MAP para esse chat.
    Se TOPIC_MAP não estiver definido/estiver vazio, considera NÃO permitido.
    """
    tm = getattr(config, "TOPIC_MAP", None)
    if not tm or topic_id is None:
        return False

    # TOPIC_MAP veio do .env (JSON); as chaves geralmente são strings
    key_candidates = [chat_id, str(chat_id)]
    for key in key_candidates:
        if key in tm:
            try:
                allowed_list = tm[key]
            except Exception:
                continue
            try:
                allowed: Set[int] = set(int(x) for x in allowed_list)
            except Exception:
                allowed = set()
            return topic_id in allowed
    return False


# ---------------- handler principal ----------------

async def on_signal_message(text: str, event) -> None:
    try:
        # Destino dinâmico resolvido pelo telegram_reader (TARGET_MAP)
        target = getattr(event, "_target_chat", config.TARGET_CHAT)
        chat_id = int(getattr(event, "chat_id", 0))
        topic_id = getattr(event, "_topic_id", None)
        chat_username = getattr(event, "_chat_username", None)

        # 1) Só age se "parecer trade"
        if not is_potential_signal(text):
            return

        # 2) Só age se o tópico estiver permitido no TOPIC_MAP
        if not _topic_allowed(chat_id, topic_id):
            log.info(f"[skip] trade detectado mas topic_id={topic_id} não está no TOPIC_MAP para chat={chat_id}")
            return

        # 3) Se configurado para "somente notificar", envia aviso e não faz forward
        notify_only = False
        # checa por (chat, topic) -> (chat, None) -> (username, topic) -> (username, None)
        if (chat_id, topic_id) in config.NOTIFY_ONLY:
            notify_only = True
        elif (chat_id, None) in config.NOTIFY_ONLY:
            notify_only = True
        elif chat_username and (chat_username, topic_id) in config.NOTIFY_ONLY:
            notify_only = True
        elif chat_username and (chat_username, None) in config.NOTIFY_ONLY:
            notify_only = True

        if notify_only:
            chat_title = getattr(event, "_chat_title", "Origem")
            topic_title = getattr(event, "_topic_title", None)
            topic_str = f" | tópico: {topic_title}" if topic_title else ""
            await event.client.send_message(
                target,
                f"🔔 Nova mensagem detectada em {chat_title}{topic_str}."
            )
        else:
            # Reencaminhar a mensagem original (com mídia) para o destino
            # (equivalente ao forward do Telegram)
            await event.client.forward_messages(
                entity=target,
                messages=event.message,
                from_peer=event.chat_id
            )

        # 4) Extras: tenta parse (estrito -> flexível)
        parsed_ok = True
        try:
            signal = parse_signal(text)
        except Exception:
            try:
                signal = parse_signal_flexible(text)
            except Exception:
                parsed_ok = False

        # Se não conseguiu parsear, ainda assim envie um extra curtinho
        if not parsed_ok:
            await event.client.send_message(
                target,
                "⚠️ Sinal detectado, mas não consegui interpretar os campos (formato não suportado)."
            )
            return

        # 5) Validação local (regras determinísticas)
        issues = local_validate(signal)

        # 6) Profile + alocação
        profile = choose_tp_profile(
            signal=signal,
            default_profile=config.TP_PROFILE,
            auto_threshold_pct=config.TP_AUTO_THRESHOLD_PCT,
            kw_scalp=config.TP_KEYWORD_SCALP,
            kw_swing=config.TP_KEYWORD_SWING,
            original_text=text
        )
        alloc = alloc_for_signal(signal, profile)

        # 7) Observações do Gemini (opcional)
        note = gemini_validate(signal, text)

        # 8) Plano de ordens (mock)
        cfg = PlanConfig(
            tp_alloc=alloc,
            risk_pct=config.DEFAULT_RISK_PCT,
            balance_usdt=config.DEFAULT_BALANCE_USDT,
            price_precision=config.PRICE_PRECISION,
            qty_precision=config.QTY_PRECISION,
            use_post_only=True
        )
        orders: List[Order] = build_order_plan(signal, cfg, symbol_suffix=config.SYMBOL_SUFFIX)

        # 9) Monta os EXTRAS (sem nome de chat/tópico)
        parts = []

        if issues:
            parts.append("⚠️ **Validação local encontrou problemas:**\n- " + "\n- ".join(issues))
        else:
            parts.append("✅ **Validação local OK.**")

        if note:
            parts.append("🤖 **Gemini:** " + note)

        parts.append(f"📌 **Profile escolhido:** {profile}")
        parts.append(f"📊 **Sinal parseado:**\n`{signal}`")

        plan_txt = "\n".join(str(o) for o in orders)
        parts.append("🧾 **Plano de ordens (mock):**\n```\n" + plan_txt + "\n```")

        final_msg = "\n\n".join(parts)

        # 10) Envia os extras (em uma segunda mensagem, logo após o forward)
        await event.client.send_message(target, final_msg)

        # (Mock) envio para Bybit – substitua quando integrar de verdade
        bybit.place_orders(orders)

    except Exception as e:
        target = getattr(event, "_target_chat", config.TARGET_CHAT)
        await event.client.send_message(target, f"⚠️ Erro ao processar mensagem: {e}")
        log.exception(e)


# ---------------- boot/loop ----------------

async def main():
    client = start_listening(on_signal_message)
    # Garante sessão antes de ficar aguardando eventos
    await ensure_login()
    await run_forever(client)

if __name__ == "__main__":
    asyncio.run(main())