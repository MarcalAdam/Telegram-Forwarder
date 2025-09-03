import os
from dataclasses import asdict
from typing import Optional, List
from models import TradeSignal
import google.generativeai as genai
import config

def local_validate(signal: TradeSignal) -> List[str]:
    issues = []

    # PM deve estar dentro do range
    if not (min(signal.entry_low, signal.entry_high) <= signal.entry_pm <= max(signal.entry_low, signal.entry_high)):
        issues.append("PM fora do range de entrada informado.")

    side = signal.side.upper()
    pm = signal.entry_pm

    if side == "SHORT":
        # SL deve ser ACIMA do PM; TPs devem ser ABAIXO do PM
        if signal.sl <= pm:
            issues.append("Para SHORT, o SL deve estar ACIMA do PM.")
        for i, tp in enumerate(signal.tps, 1):
            if tp >= pm:
                issues.append(f"Para SHORT, o TP{i} deve estar ABAIXO do PM.")
    elif side == "LONG":
        # SL deve ser ABAIXO do PM; TPs devem ser ACIMA do PM
        if signal.sl >= pm:
            issues.append("Para LONG, o SL deve estar ABAIXO do PM.")
        for i, tp in enumerate(signal.tps, 1):
            if tp <= pm:
                issues.append(f"Para LONG, o TP{i} deve estar ACIMA do PM.")
    else:
        issues.append("Side inválido (esperado LONG ou SHORT).")

    return issues

def setup_gemini():
    if not config.GEMINI_API_KEY:
        return None
    genai.configure(api_key=config.GEMINI_API_KEY)
    return genai.GenerativeModel(config.GEMINI_MODEL)

_model = setup_gemini()

def gemini_validate(signal: TradeSignal, original_text: str) -> Optional[str]:
    if not _model:
        return None
    prompt = f"""
Você é um assistente que apenas adiciona observações.
NÃO repita validações já cobertas por regras fixas:

REGRAS FIXAS (já aplicadas):
- Para SHORT: SL acima do PM, TPs abaixo do PM.
- Para LONG:  SL abaixo do PM, TPs acima do PM.

Ou seja, se esses critérios forem atendidos, NÃO diga que há erro. 
Se quiser, pode elogiar ("configuração correta para SHORT") ou sugerir ajustes secundários 
(ex.: range de entrada muito largo, alavancagem agressiva, TP muito distante).

Texto original entre <<<>>>:

<<<
{original_text}
>>>

Extraído (JSON):
{asdict(signal)}

Responda em 2-5 linhas, objetivo, seguindo as regras acima.
    """.strip()
    try:
        r = _model.generate_content(prompt)
        return (r.text or "").strip()
    except Exception as e:
        return f"[Gemini OFF] Erro ao validar: {e}"
