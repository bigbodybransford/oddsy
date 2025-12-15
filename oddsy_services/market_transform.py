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

def build_kalshi_display_df(df_display: pd.DataFrame) -> pd.DataFrame:
    df = df_display.copy()

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

def _best_prices_from_book(book: dict):
    """
    book has bids/asks arrays; take best level 0 price if present.
    Prices are in 0..1 (USDC probability-style), convert later.
    """
    best_bid = None
    best_ask = None

    try:
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        if bids:
            best_bid = float(bids[0].get("price"))
        if asks:
            best_ask = float(asks[0].get("price"))
    except Exception:
        pass

    return best_bid, best_ask

def build_polymarket_display_df(gamma_df: pd.DataFrame, books_by_token: dict) -> pd.DataFrame:
    """
    Explode Gamma market rows into outcome rows so the UI grouping works like Kalshi:
    - One 'event' card (event_ticker) containing multiple 'outcomes' rows.
    """
    if gamma_df is None or gamma_df.empty:
        return pd.DataFrame()

    rows = []

    for _, m in gamma_df.iterrows():
        question = m.get("question") or m.get("title") or m.get("slug") or "Polymarket market"
        category = m.get("category")
        close_time = m.get("endDateIso") or m.get("endDate") or m.get("closedTime")
        condition_id = m.get("conditionId")  # stable-ish unique id :contentReference[oaicite:9]{index=9}
        slug = m.get("slug")

        # Prefer volume24hrClob if present, else volume24hr
        vol_24h = m.get("volume24hrClob")
        if vol_24h is None:
            vol_24h = m.get("volume24hr")

        # outcomes & prices
        outcomes = m.get("outcomes")
        outcome_prices = m.get("outcomePrices")
        clob_token_ids = m.get("clobTokenIds")

        # These are often strings that look like JSON arrays in Gamma
        import json
        def parse_listish(x):
            if x is None:
                return []
            if isinstance(x, list):
                return x
            if isinstance(x, str) and x.strip().startswith("["):
                try:
                    return json.loads(x)
                except Exception:
                    return []
            return []

        outcomes = parse_listish(outcomes)
        outcome_prices = parse_listish(outcome_prices)
        token_ids = parse_listish(clob_token_ids)

        # fallback if prices missing or mismatched
        if len(outcome_prices) != len(outcomes):
            outcome_prices = [None] * len(outcomes)

        # Map each outcome -> a row that looks like your Kalshi df_display row
        for i, outcome in enumerate(outcomes):
            token_id = str(token_ids[i]) if i < len(token_ids) else None

            yes_bid = None
            yes_ask = None
            last_traded = None

            if token_id and token_id in books_by_token:
                b = books_by_token[token_id]
                best_bid, best_ask = _best_prices_from_book(b)
                yes_bid = best_bid
                yes_ask = best_ask

            # If we didn’t get bid/ask, use Gamma’s outcomePrices as a midpoint-ish estimate
            mid = None
            try:
                if yes_bid is not None and yes_ask is not None:
                    mid = (yes_bid + yes_ask) / 2.0
                elif yes_bid is not None:
                    mid = yes_bid
                elif yes_ask is not None:
                    mid = yes_ask
            except Exception:
                mid = None

            if mid is None:
                try:
                    op = outcome_prices[i]
                    if op is not None:
                        mid = float(op)
                except Exception:
                    mid = None

            implied_yes_prob = None
            if mid is not None and not np.isnan(mid):
                implied_yes_prob = round(mid * 100.0, 1)

            rows.append({
                # event grouping key for Polymarket (we'll refine later for cross-platform matching)
                "event_ticker": str(slug or condition_id or question),

                "title": question,
                "subtitle": None,
                "ticker": str(token_id or f"{condition_id}:{outcome}"),

                "category": category,
                "market_type": "categorical" if len(outcomes) > 2 else "binary",
                "status": "open" if not m.get("closed") else "closed",
                "close_time": close_time,

                # percent fields your UI expects
                "yes_bid_pct": None if yes_bid is None else round(yes_bid * 100.0, 1),
                "yes_ask_pct": None if yes_ask is None else round(yes_ask * 100.0, 1),
                "last_traded_pct": None if last_traded is None else round(last_traded * 100.0, 1),

                # the one your UI uses
                "implied_yes_prob": implied_yes_prob,

                # used for sorting events
                "volume_24h": vol_24h if vol_24h is not None else 0,

                # for labels (your outcome_label uses yes_sub_title)
                "yes_sub_title": str(outcome),

                "platform": "Polymarket",
            })

    df = pd.DataFrame(rows)
    return df