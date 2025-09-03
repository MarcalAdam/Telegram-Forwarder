# parser_signal.py
import re
from typing import List, Optional
from models import TradeSignal

NUM = r"[-+]?\d+(?:[.,]\d+)?"

def _n(x: str) -> float:
    return float(x.replace(",", "."))

def is_potential_signal(text: str) -> bool:
    """
    Heurística leve para decidir se o texto parece um 'sinal de trade'.
    Aceita variações como: LONG/SHORT, Entrada, TP/TPs, SL, 'Entradas Escalonadas', etc.
    """
    t = text.lower()
    has_side = ("long" in t) or ("short" in t)
    has_entry = ("entrada" in t) or ("entradas escalonadas" in t) or ("entry" in t)
    has_tp = ("tp" in t) or ("tps" in t)
    has_sl = ("sl" in t) or ("stop" in t)
    # exemplos como "Entrada: 0.027 (mercado)" também contam
    return has_side and (has_entry or has_tp or has_sl)

def parse_signal(text: str) -> TradeSignal:
    """
    (SEU PARSER ESTRITO ATUAL)
    Mantém como já estava – não removi nada aqui no seu projeto.
    """
    # ... (seu código atual do parse estrito)
    raise NotImplementedError  # deixar aqui só para lembrar que já existe no seu arquivo

def parse_signal_flexible(text: str) -> TradeSignal:
    """
    Parser mais tolerante, cobrindo variações:
    - 'LONG $POPCAT/USDT' (extrai POPCAT)
    - '🟢 LONG – SOLUSDT' (extrai SOL)
    - 'Entrada: 0.027 (mercado)' -> pm = 0.027 e range = [0.027, 0.027]
    - 'Entradas Escalonadas: 173.50-177.00' -> range e pm = média
    - 'TPs: 0.3296, 0.3380, ...' -> lista
    - 'TP1/TP2/TP3 ...' -> lista
    - 'Alavancagem: 3x a 15x' ou 'Alavancagem: 5x'
    """
    raw = text.strip()

    # 1) Side e Símbolo
    m_side = re.search(r"\b(LONG|SHORT)\b", raw, flags=re.I)
    if not m_side:
        raise ValueError("Não encontrei LONG/SHORT.")
    side = m_side.group(1).upper()

    # símbolos possíveis
    # ex: LONG $POPCAT/USDT  |  LONG – SOLUSDT  |  LONG SOL USDT
    sym = None
    # $COIN/USDT
    m_sym1 = re.search(r"\b(?:LONG|SHORT)\b\s+\$?([A-Z0-9]{2,15})(?:/USDT|USDT)?", raw, flags=re.I)
    if m_sym1:
        sym = m_sym1.group(1).upper()
    # fallback: pegar palavra em CAPS seguida de USDT
    if not sym:
        m_sym2 = re.search(r"\b([A-Z0-9]{2,15})USDT\b", raw)
        if m_sym2:
            sym = m_sym2.group(1).upper()
    if not sym:
        # último recurso: palavra maiúscula de 2-10 letras depois de LONG/SHORT
        m_sym3 = re.search(r"\b(?:LONG|SHORT)\b\s+([A-Z]{2,10})\b", raw)
        if m_sym3:
            sym = m_sym3.group(1).upper()
    if not sym:
        raise ValueError("Não consegui inferir o símbolo.")

    # 2) Entrada / Entradas Escalonadas
    entry_low = entry_high = entry_pm = None

    # Entradas Escalonadas: 173.50-177.00
    m_esc = re.search(r"Entradas?\s+Escalonadas?\s*:\s*(" + NUM + r")\s*[-–]\s*(" + NUM + r")", raw, flags=re.I)
    if m_esc:
        a = _n(m_esc.group(1)); b = _n(m_esc.group(2))
        entry_low, entry_high = min(a, b), max(a, b)
        entry_pm = (entry_low + entry_high) / 2.0

    # Entrada: a - b (pm: x)  (formato clássico)
    if entry_pm is None:
        m_ent = re.search(r"Entrada\s*:\s*(" + NUM + r")\s*[-–]\s*(" + NUM + r")\s*(?:\((?:pm|média)\s*:\s*(" + NUM + r")\))?", raw, flags=re.I)
        if m_ent:
            a = _n(m_ent.group(1)); b = _n(m_ent.group(2))
            entry_low, entry_high = min(a, b), max(a, b)
            if m_ent.group(3):
                entry_pm = _n(m_ent.group(3))
            else:
                entry_pm = (entry_low + entry_high) / 2.0

    # Entrada: valor único (mercado)
    if entry_pm is None:
        m_one = re.search(r"Entrada\s*:\s*(" + NUM + r")", raw, flags=re.I)
        if m_one:
            v = _n(m_one.group(1))
            entry_low = entry_high = entry_pm = v

    if entry_pm is None:
        # Em falta de 'Entrada', usa média entre TP1 e preço atual? Aqui não: pede explicitamente.
        raise ValueError("Não consegui ler a Entrada/Entradas Escalonadas.")

    # 3) SL
    m_sl = re.search(r"\bSL\s*:\s*(" + NUM + r")", raw, flags=re.I)
    if not m_sl:
        # aceitar 'Stop:' ou 'Stop Loss:'
        m_sl = re.search(r"\bStop(?:\s*Loss)?\s*:\s*(" + NUM + r")", raw, flags=re.I)
    if not m_sl:
        raise ValueError("Não encontrei SL.")
    sl = _n(m_sl.group(1))

    # 4) TPs
    tps: List[float] = []

    # TPs: v1, v2, v3 ...
    m_tps_list = re.search(r"\bTPs?\s*:\s*([^\n\r]+)", raw, flags=re.I)
    if m_tps_list:
        # pega linha após "TPs:" e extrai números
        chunk = m_tps_list.group(1)
        for m in re.finditer(NUM, chunk):
            tps.append(_n(m.group(0)))

    # TP1: v  | TP2: v ...
    if not tps:
        for m in re.finditer(r"\bTP\d+\s*:\s*(" + NUM + r")", raw, flags=re.I):
            tps.append(_n(m.group(1)))

    if not tps:
        raise ValueError("Não encontrei TPs.")

    # 5) Alavancagem
    lev_min = lev_max = None
    m_lev1 = re.search(r"Alavancagem\s*:\s*(" + NUM + r")\s*[xX]\s*(?:a|–|-|to|até)\s*(" + NUM + r")\s*[xX]?", raw, flags=re.I)
    if m_lev1:
        lev_min, lev_max = _n(m_lev1.group(1)), _n(m_lev1.group(2))
    else:
        # Alavancagem: 5x
        m_lev2 = re.search(r"Alavancagem\s*:\s*(" + NUM + r")\s*[xX]\b", raw, flags=re.I)
        if m_lev2:
            lev_min = _n(m_lev2.group(1))
            lev_max = lev_min

    # 6) Tags/Notas
    tags = re.findall(r"#\w+", raw)

    return TradeSignal(
        side=side, symbol=sym,
        entry_low=entry_low, entry_high=entry_high, entry_pm=entry_pm,
        sl=sl, lev_min=lev_min, lev_max=lev_max,
        tps=tps, tags=tags
    )