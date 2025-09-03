from dataclasses import dataclass
from typing import List, Optional

@dataclass
class TradeSignal:
    side: str                 # "LONG" ou "SHORT"
    symbol: str               # "ETH", "BTC", etc
    entry_low: float
    entry_high: float
    entry_pm: float
    sl: float
    lev_min: Optional[float]
    lev_max: Optional[float]
    tps: List[float]
    tags: List[str]
    notes: Optional[str] = None

@dataclass
class PlanConfig:
    tp_alloc: List[float]                 # somar 1.0
    risk_pct: Optional[float] = None
    balance_usdt: Optional[float] = None
    price_precision: int = 2
    qty_precision: int = 4
    use_post_only: bool = True

@dataclass
class Order:
    type: str                # "LIMIT" / "MARKET" / "STOP"
    side: str                # "Buy" / "Sell"
    symbol: str              # "ETHUSDT"
    price: Optional[float]
    qty: float
    tag: str                 # "ENTRY" / "TP1"... / "SL"
    reduce_only: bool = False
    post_only: bool = False
