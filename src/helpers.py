# helpers.py
from typing import List
from models import TradeSignal, PlanConfig, Order

def _alloc_by_profile(num_tps: int, profile: str) -> List[float]:
    if num_tps == 3:
        return [0.50, 0.25, 0.25] if profile == "50_25_25" else [0.35, 0.35, 0.30]
    if num_tps == 4:
        return [0.35, 0.35, 0.15, 0.15]
    return [1.0 / num_tps] * num_tps

def choose_tp_profile(signal: TradeSignal, default_profile: str, auto_threshold_pct: float,
                      kw_scalp: str, kw_swing: str, original_text: str) -> str:
    """
    Regra de escolha do profile por:
    1) Palavra-chave no texto/tags (#scalp / #swing) override.
    2) Se default_profile == "auto": decide por distância relativa do TP1 a partir do PM.
    3) Caso contrário, usa o default_profile fixo.
    """
    text_lc = (original_text or "").lower()
    tags_lc = " ".join(signal.tags).lower()

    # Override por keyword
    if kw_scalp and (kw_scalp in text_lc or kw_scalp in tags_lc):
        return "scalp_mack"
    if kw_swing and (kw_swing in text_lc or kw_swing in tags_lc):
        return "50_25_25"

    if default_profile != "auto":
        return default_profile

    # Auto: distância percentual do TP1 ao PM
    if not signal.tps:
        return "scalp_mack"  # fallback inofensivo

    tp1 = signal.tps[0]
    pm = signal.entry_pm
    if pm <= 0:
        return "scalp_mack"

    dist_pct = abs(tp1 - pm) / pm * 100.0
    if dist_pct >= auto_threshold_pct:
        return "50_25_25"
    return "scalp_mack"

def alloc_for_signal(signal: TradeSignal, profile: str) -> List[float]:
    return _alloc_by_profile(len(signal.tps), profile)

def calc_qty(balance_usdt: float, risk_pct: float, pm: float, sl: float) -> float:
    dist = abs(sl - pm)
    if dist <= 0:
        raise ValueError("PM e SL inválidos para cálculo de quantidade.")
    return (balance_usdt * risk_pct) / dist

def build_order_plan(signal: TradeSignal, cfg: PlanConfig, symbol_suffix: str = "USDT") -> list:
    from models import Order  # evitar import circular

    qty_total = calc_qty(cfg.balance_usdt, cfg.risk_pct, signal.entry_pm, signal.sl) if (cfg.balance_usdt and cfg.risk_pct) else 0.0
    symbol = signal.symbol.upper() + symbol_suffix
    side_entry = "Sell" if signal.side.upper() == "SHORT" else "Buy"
    side_tp = "Buy" if side_entry == "Sell" else "Sell"

    orders: list = []
    # Entrada no PM (limit)
    orders.append(Order(
        type="LIMIT", side=side_entry, symbol=symbol,
        price=round(signal.entry_pm, cfg.price_precision),
        qty=round(qty_total, cfg.qty_precision) if qty_total else 0.0,
        tag="ENTRY", reduce_only=False, post_only=cfg.use_post_only
    ))
    # TPs
    for i, (tp_price, frac) in enumerate(zip(signal.tps, cfg.tp_alloc), start=1):
        q = qty_total * frac if qty_total else 0.0
        orders.append(Order(
            type="LIMIT", side=side_tp, symbol=symbol,
            price=round(tp_price, cfg.price_precision),
            qty=round(q, cfg.qty_precision),
            tag=f"TP{i}", reduce_only=True, post_only=cfg.use_post_only
        ))
    # SL
    orders.append(Order(
        type="STOP", side=side_tp, symbol=symbol,
        price=round(signal.sl, cfg.price_precision),
        qty=round(qty_total, cfg.qty_precision),
        tag="SL", reduce_only=True, post_only=False
    ))
    return orders

def normalize_sources(raw_sources, fallback_source=None):
    """
    Normaliza lista de chats (IDs ou @usernames).
    - raw_sources: pode ser str separada por vírgula, list, None
    - fallback_source: usado se raw_sources for vazio (ex.: SOURCE_CHAT único)
    """
    if isinstance(raw_sources, str):
        sources = [s.strip() for s in raw_sources.split(",") if s.strip()]
    else:
        sources = list(raw_sources) if raw_sources else []

    if not sources and fallback_source:
        sources = [fallback_source]

    norm = set()
    for s in sources:
        if isinstance(s, int) or (isinstance(s, str) and s.lstrip("-").isdigit()):
            norm.add(int(s))
        elif isinstance(s, str):
            norm.add(s.lstrip("@").lower())
    return norm


def normalize_topic_map(raw_topic_map, fallback_chat=None, fallback_topic=None):
    """
    Normaliza mapa de tópicos {chat: [topic_ids]}.
    - Aceita dict, ou usa fallback_chat + fallback_topic.
    """
    norm = {}
    if isinstance(raw_topic_map, dict):
        for k, v in raw_topic_map.items():
            # normaliza chave
            if isinstance(k, int) or (isinstance(k, str) and k.lstrip("-").isdigit()):
                key = int(k)
            else:
                key = str(k).lstrip("@").lower()
            # normaliza lista de tópicos
            tops = set(int(t) for t in v if str(t).isdigit())
            if tops:
                norm[key] = tops
    elif fallback_chat and fallback_topic:
        if isinstance(fallback_chat, int) or (isinstance(fallback_chat, str) and fallback_chat.lstrip("-").isdigit()):
            key = int(fallback_chat)
        else:
            key = str(fallback_chat).lstrip("@").lower()
        norm[key] = {int(fallback_topic)}
    return norm
