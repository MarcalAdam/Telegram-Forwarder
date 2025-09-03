from typing import List
from models import Order

class BybitClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        # TODO: inicializar SDK oficial quando for ligar de verdade

    def place_orders(self, orders: List[Order]) -> None:
        # TODO: implementar integração real (REST/WebSocket) com flags reduce-only, post-only etc.
        print("=== [BybitClient] ORDERS (mock) ===")
        for o in orders:
            print(o)
