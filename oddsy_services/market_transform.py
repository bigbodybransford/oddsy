import re
import numpy as np
import pandas as pd

SHORT_CODE_RE = re.compile(r"^[A-Z]{2,6}$")
SI_SWIM_PATTERN = re.compile(
    r"^Will (.+?) be on the cover of .*Sports Illustrated Swimsuit",
    re.IGNORECASE,
)

def extract_option_name_from_title(row: dict):
    title = (row.get("title") or "").strip()
    yes_sub = (row.get("yes_sub_title") or "").strip()

    if not (yes_sub and SHORT_CODE_RE.fullmatch(yes_sub)):
        return None

    m = SI_SWIM_PATTERN.match(title)
    if m:
        return m.group(1).strip()

    return None

def compute_probability(row: dict):
    lt = row.get("last_traded_pct")
    if lt is not None and not np.isnan(lt) and lt > 0:
        return lt

    bid = row.get("yes_bid_pct")
    ask = row.get("yes_ask_pct")
    if bid is not None and ask is not None:
        if not np.isnan(bid) and not np.isnan(ask) and (bid > 0 or ask > 0):
            return round((bid + ask) / 2.0, 1)

    for v in [bid, ask]:
        if v is not None and not np.isnan(v) and v > 0:
            return v

    return None

def compute_implied_yes_prob_from_dollars(row: dict):
    """
    For Kalshi binary markets:
    - last_price_dollars -> percent
    - fallback: midpoint of yes_bid_dollars/yes_ask_dollars
    """
    mtype = row.get("market_type")
    if mtype and str(mtype).lower() != "binary":
        return None

    def to_float(x):
        if x is None:
            return None
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    last = to_float(row.get("last_price_dollars"))
    if last is not None:
        return round(last * 100.0, 1)

    yes_bid = to_float(row.get("yes_bid_dollars"))
    yes_ask = to_float(row.get("yes_ask_dollars"))

    candidates = [v for v in (yes_bid, yes_ask) if v is not None]
    if candidates:
        mid = sum(candidates) / len(candidates)
        return round(mid * 100.0, 1)

    return None

def build_kalshi_display_df(markets_df: pd.DataFrame) -> pd.DataFrame:
    df = markets_df.copy()

    cols = [
        "title","subtitle","ticker","event_ticker","category","market_type","status","close_time",
        "yes_bid_dollars","yes_ask_dollars","no_bid_dollars","no_ask_dollars",
        "last_price_dollars","volume","volume_24h","open_interest","yes_sub_title",
    ]
    existing_cols = [c for c in cols if c in df.columns]
    df = df[existing_cols]

    df["option_name_from_title"] = df.apply(lambda r: extract_option_name_from_title(r.to_dict()), axis=1)
    df["implied_yes_prob"] = df.apply(lambda r: compute_implied_yes_prob_from_dollars(r.to_dict()), axis=1)
    df["platform"] = "Kalshi"

    df_display = df.copy()
    for col in ["yes_bid_dollars","yes_ask_dollars","no_bid_dollars","no_ask_dollars","last_price_dollars"]:
        if col in df_display.columns:
            df_display[col] = (df_display[col].astype(float) * 100).round(1)

    df_display = df_display.rename(columns={
        "yes_bid_dollars":"yes_bid_pct",
        "yes_ask_dollars":"yes_ask_pct",
        "no_bid_dollars":"no_bid_pct",
        "no_ask_dollars":"no_ask_pct",
        "last_price_dollars":"last_traded_pct",
    })

    df_display["implied_prob_pct"] = df_display.apply(lambda r: compute_probability(r.to_dict()), axis=1)

    # ensure event_ticker exists
    if "event_ticker" not in df_display.columns:
        df_display["event_ticker"] = df_display.get("ticker")

    return df_display