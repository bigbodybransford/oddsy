import os
import requests
import pandas as pd

POLYMARKET_BASE_URL = os.getenv("POLYMARKET_BASE_URL", "https://clob.polymarket.com")

def polymarket_get(path: str, params: dict | None = None) -> dict:
    url = POLYMARKET_BASE_URL.rstrip("/") + path
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_polymarket_markets(limit: int = 200) -> pd.DataFrame:
    return pd.DataFrame()