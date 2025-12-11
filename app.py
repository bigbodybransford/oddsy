import streamlit as st
import pandas as pd
import requests
import os
import datetime
import base64

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv
from oddsy_services.stats_service import get_top_level_stats
from ui.components.stats_bar import render_stats_bar

load_dotenv()

API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
PRIVATE_KEY_PATH = os.getenv("KALSHI_API_PRIVATE_KEY")
PRIVATE_KEY_PEM = os.getenv("KALSHI_API_PRIVATE_KEY_PEM")
BASE_URL = "https://demo-api.kalshi.co"

def load_private_key_from_path(key_path: str):
    """Load the Kalshi private key from a file path (local dev)."""
    if not key_path:
        raise RuntimeError("KALSHI_API_PRIVATE_KEY (path) is not set in .env")

    with open(key_path, "rb") as f:
        return serialization.load_pem_private_key(
            f.read(),
            password=None,
            backend=default_backend(),
        )

def load_private_key_from_pem(pem_data: str):
    """Load the Kalshi private key directly from PEM text (for cloud)."""
    if not pem_data:
        raise RuntimeError("KALSHI_API_PRIVATE_KEY_PEM is not set")
    return serialization.load_pem_private_key(
        pem_data.encode("utf-8"),
        password=None,
        backend=default_backend(),
    )
    
# Decide which source to use: PEM string (cloud) or file path (local)
if PRIVATE_KEY_PEM:
    PRIVATE_KEY = load_private_key_from_pem(PRIVATE_KEY_PEM)
else:
    PRIVATE_KEY = load_private_key_from_path(PRIVATE_KEY_PATH)

def create_signature(private_key, timestamp: str, method: str, path: str) -> str:
    """Create the request signature according to Kalshi docs."""
    # Strip query parameters before signing
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

def kalshi_get(path: str):
    """
    Make an authenticated GET request to Kalshi.
    `path` must start with /trade-api/v2/...
    """
    if not API_KEY_ID:
        raise RuntimeError("KALSHI_API_KEY_ID is not set in .env")

    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))  # ms
    signature = create_signature(PRIVATE_KEY, timestamp, "GET", path)

    headers = {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }

    response = requests.get(BASE_URL + path, headers=headers)
    response.raise_for_status()
    return response.json()


def fetch_kalshi_markets(status: str = "open", max_pages: int = 5, page_limit: int = 500):
    # Fetch markets from Kalshi with pagination and safety guards.

    # - status: "open", "closed", etc. (depends on what you want)
    # - max_pages: safety cap so we do not loop forever
    # - page_limit: per-page limit

    # Returns a normalized DataFrame of all markets fetched.
    
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
        
        try:
            data = kalshi_get(path)
        except Exception as e:
            print(f"Error fetching markets page {pages_fetched}: {e}")
            break
        
        markets = data.get("markets", data)
        if not markets:
            break
        
        all_markets.extend(markets)
        
        cursor = data.get("cursor")
        if not cursor:
            break
        
    if not all_markets:
        return pd.DataFrame()
        
    return pd.json_normalize(markets)

def inspect_kalshi_categories(df):
    if "category" not in df.columns:
        st.warning("No 'category' column found in markets_df")
        return

    cats = sorted(df["category"].fillna("unknown").unique().tolist())
    st.write("Detected categories:", cats)

def fetch_kalshi_trades_last_week(max_pages: int = 5):
    
    # Fetch all trades from the last 7 days w/ safety guards:
    # - Limit the number of pages (max_pages)
    # - Handles errors so Streamlit doesn't run infinitely
    
    # Kalshi expects Unix timestamps (seconds, UTC)
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
        
        try:
            data = kalshi_get(path)
        except Exception as e:
            print(f"Error fetching trades page {pages_fetched}: {e}")
            break
        
        trades = data.get("trades", [])
        all_trades.extend(trades)

        cursor = data.get("cursor")
        if not cursor:  # when cursor is empty / null, no more pages
            break

    if not all_trades:
        return pd.DataFrame()

    return pd.json_normalize(all_trades)

st.set_page_config(page_title="Prediction Markets MVP", layout="wide")
st.title("Prediction Market Terminal (Kalshi - Public Endpoint MVP)")
st.write("Data from Kalshi elections API.")

if st.button("Refresh Data"):
    # You can choose status="open" or "" to get all
    markets_df = fetch_kalshi_markets(status="open", max_pages=5, page_limit=500)
    trades_df = fetch_kalshi_trades_last_week(max_pages=5)
    
    st.session_state["markets_df"] = markets_df
    st.session_state["trades_df"] = trades_df
    
    st.success("Fetched latest markets and trades!")

markets_df = st.session_state.get("markets_df")
trades_df = st.session_state.get("trades_df")

markets_df = st.session_state.get("markets_df")
trades_df = st.session_state.get("trades_df")

if markets_df is None:
    st.info("Click 'Refresh Data' to load markets.")
else:
    # Basic debug
    st.write(
        "DEBUG: markets_df rows =", len(markets_df),
        "| trades_df rows =", 0 if trades_df is None else len(trades_df)
    )

    # Just show the raw markets_df for now
    st.write("DEBUG: showing raw markets_df with no filters or transforms")
    st.write(f"DEBUG: markets_df columns = {list(markets_df.columns)}")

    st.write(f"Showing {len(markets_df)} raw markets")
    st.dataframe(markets_df.reset_index(drop=True), use_container_width=True)
