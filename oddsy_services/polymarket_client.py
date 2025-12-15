import os
import json
import time
import datetime
import requests
import pandas as pd

GAMMA_BASE_URL = os.getenv("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
CLOB_BASE_URL  = os.getenv("POLYMARKET_CLOB_URL",  "https://clob.polymarket.com")
DATA_API_BASE_URL = os.getenv("POLYMARKET_DATA_API_URL", "https://data-api.polymarket.com")

def _get(url: str, params: dict | None = None):
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def _post(url: str, payload):
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_gamma_markets(
    limit: int = 200,
    max_pages: int = 5,
    closed: bool = False,
    active: bool = True,
) -> pd.DataFrame:
    """
    Gamma GET /markets supports pagination via limit + offset. :contentReference[oaicite:3]{index=3}
    """
    all_rows = []
    offset = 0

    for _ in range(max_pages):
        params = {
            "limit": limit,
            "offset": offset,
            "closed": closed,
            "active": active,
        }
        rows = _get(f"{GAMMA_BASE_URL}/markets", params=params)
        if not rows:
            break

        all_rows.extend(rows)
        offset += limit
        time.sleep(0.05)  # tiny politeness pause

    return pd.DataFrame(all_rows)

def _parse_listish(x):
    """
    Gamma often returns outcomes/outcomePrices/clobTokenIds as strings.
    We parse JSON arrays when possible.
    """
    if x is None:
        return None
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        s = x.strip()
        # common case: '["A","B"]' or '[0.4,0.6]'
        if s.startswith("[") and s.endswith("]"):
            try:
                return json.loads(s)
            except Exception:
                return None
        # sometimes comma-separated
        if "," in s:
            return [p.strip() for p in s.split(",") if p.strip()]
    return None

def fetch_clob_books(token_ids: list[str], chunk_size: int = 75) -> dict:
    """
    POST /books expects a JSON array body:
    [
      {"token_id": "123"},
      {"token_id": "456"}
    ]
    :contentReference[oaicite:2]{index=2}
    """
    out = {}
    for i in range(0, len(token_ids), chunk_size):
        chunk = token_ids[i : i + chunk_size]

        # IMPORTANT: body is a LIST, not {"params": ...}
        payload = [{"token_id": str(t)} for t in chunk]

        try:
            books = _post(f"{CLOB_BASE_URL}/books", payload)
        except requests.HTTPError as e:
            # surface the response body so we can see exactly what it disliked
            body = ""
            try:
                body = e.response.text
            except Exception:
                pass
            raise RuntimeError(f"/books 400. Body: {body}") from e

        # Response is usually a list of book summaries; map by token id
        if isinstance(books, list):
            for b in books:
                tid = str(b.get("token_id") or b.get("asset_id") or "")
                if tid:
                    out[tid] = b
        elif isinstance(books, dict):
            out.update(books)

    return out

def fetch_polymarket_markets(limit: int = 200, max_pages: int = 5):
    """
    - Gamma markets for metadata + volume24hr :contentReference[oaicite:6]{index=6}
    - CLOB books for pricing (bid/ask) :contentReference[oaicite:7]{index=7}
    Returns: (gamma_df, books_by_token_id)
    """
    gamma_df = fetch_gamma_markets(limit=limit, max_pages=max_pages, closed=False, active=True)

    if gamma_df.empty:
        return gamma_df, {}

    # collect token ids from Gamma
    token_ids = []
    if "clobTokenIds" in gamma_df.columns:
        for v in gamma_df["clobTokenIds"].tolist():
            ids = _parse_listish(v) or []
            for tid in ids:
                token_ids.append(str(tid))

    token_ids = sorted(set(token_ids))
    books_by_token = fetch_clob_books(token_ids) if token_ids else {}

    return gamma_df, books_by_token

DATA_API_BASE_URL = os.getenv("POLYMARKET_DATA_API_URL", "https://data-api.polymarket.com")


def _last_complete_week_utc():
    """
    Returns (start_ts, end_ts) for the last complete ISO week in UTC.
    ISO week = Monday 00:00:00 -> next Monday 00:00:00.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    this_monday = (now - datetime.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    last_monday = this_monday - datetime.timedelta(days=7)
    return int(last_monday.timestamp()), int(this_monday.timestamp())

def fetch_polymarket_trades_last_7d(limit=500, max_pages=50):
    """
    Data-API trades are ordered by timestamp desc (newest first). :contentReference[oaicite:4]{index=4}
    There is no timestamp filter param, so we page until we hit the cutoff.

    Returns a DataFrame of trades from the last 7 days (best-effort).
    """
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    cutoff = now - 7 * 24 * 60 * 60

    all_rows = []
    offset = 0

    for page in range(max_pages):
        params = {"limit": limit, "offset": offset}
        url = "https://data-api.polymarket.com/trades"
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()

        batch = r.json()
        if not isinstance(batch, list) or len(batch) == 0:
            break

        # Convert to DF for filtering
        dfb = pd.DataFrame(batch)
        if "timestamp" not in dfb.columns:
            # Unexpected schema — bail safely
            break

        # Keep only last 7 days
        df_keep = dfb[dfb["timestamp"].astype(int) >= cutoff]
        all_rows.append(df_keep)

        # Stop when the batch is already older than cutoff (since sorted desc)
        oldest_ts = int(dfb["timestamp"].min())
        if oldest_ts < cutoff:
            break

        offset += limit  # IMPORTANT: step by page size, not 1000 blindly

    out = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    return out

def fetch_polymarket_open_interest():
    """
    Returns open interest entries from Data-API.
    If the API returns a GLOBAL row, we’ll use that later; otherwise sum markets.
    """
    url = "https://data-api.polymarket.com/oi"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    return pd.DataFrame(data) if isinstance(data, list) else pd.DataFrame()