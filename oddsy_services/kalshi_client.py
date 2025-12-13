import os
import datetime
import base64
import pandas as pd
import requests

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

BASE_URL = "https://api.elections.kalshi.com"

def load_private_key_from_path(key_path: str):
    if not key_path:
        raise RuntimeError("KALSHI_API_PRIVATE_KEY (path) is not set in .env")
    with open(key_path, "rb") as f:
        return serialization.load_pem_private_key(
            f.read(),
            password=None,
            backend=default_backend(),
        )

def load_private_key_from_pem(pem_data: str):
    if not pem_data:
        raise RuntimeError("KALSHI_API_PRIVATE_KEY_PEM is not set")
    return serialization.load_pem_private_key(
        pem_data.encode("utf-8"),
        password=None,
        backend=default_backend(),
    )

def create_signature(private_key, timestamp: str, method: str, path: str) -> str:
    path_without_query = path.split("?")[0]
    message = f"{timestamp}{method}{path_without_query}".encode("utf-8")

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")

def kalshi_get(path: str) -> dict:
    api_key_id = os.getenv("KALSHI_API_KEY_ID")
    private_key_path = os.getenv("KALSHI_API_PRIVATE_KEY")
    private_key_pem = os.getenv("KALSHI_API_PRIVATE_KEY_PEM")

    if not api_key_id:
        raise RuntimeError("KALSHI_API_KEY_ID is not set in .env")

    # load key
    if private_key_pem:
        private_key = load_private_key_from_pem(private_key_pem)
    else:
        private_key = load_private_key_from_path(private_key_path)

    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))  # ms
    signature = create_signature(private_key, timestamp, "GET", path)

    headers = {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }

    url = BASE_URL + path
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_kalshi_markets(status: str = "open", max_pages: int = 5, page_limit: int = 500) -> pd.DataFrame:
    all_markets = []
    cursor = None
    pages_fetched = 0

    while True:
        pages_fetched += 1
        if pages_fetched > max_pages:
            break

        query = f"?limit={page_limit}"
        if status:
            query += f"&status={status}"
        if cursor:
            query += f"&cursor={cursor}"

        path = f"/trade-api/v2/markets{query}"
        data = kalshi_get(path)

        markets = data.get("markets", data)
        if not markets:
            break

        all_markets.extend(markets)

        cursor = data.get("cursor")
        if not cursor:
            break

    if not all_markets:
        return pd.DataFrame()

    return pd.json_normalize(all_markets)

def fetch_kalshi_trades_last_week(max_pages: int = 5) -> pd.DataFrame:
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now = int(now_dt.timestamp())
    week_ago = now - 7 * 24 * 60 * 60

    all_trades = []
    cursor = None
    limit = 500
    pages_fetched = 0

    while True:
        pages_fetched += 1
        if pages_fetched > max_pages:
            break

        query = f"?limit={limit}&min_ts={week_ago}&max_ts={now}"
        if cursor:
            query += f"&cursor={cursor}"

        path = f"/trade-api/v2/markets/trades{query}"
        data = kalshi_get(path)

        trades = data.get("trades", [])
        all_trades.extend(trades)

        cursor = data.get("cursor")
        if not cursor:
            break

    if not all_trades:
        return pd.DataFrame()

    return pd.json_normalize(all_trades)