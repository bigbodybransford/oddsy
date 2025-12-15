# oddsy_services/stats_service.py

from dataclasses import dataclass
from typing import Optional
import pandas as pd


# ---------------------------
# Data models
# ---------------------------

@dataclass
class ExchangeStats:
    name: str
    weekly_notional_volume: float
    active_markets: int
    weekly_transactions: int
    open_interest: float


@dataclass
class TopLevelStats:
    kalshi: ExchangeStats
    polymarket: Optional[ExchangeStats] = None  # for later


# ---------------------------
# Stats computation
# ---------------------------

def compute_kalshi_stats(
    markets_df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame] = None,
) -> ExchangeStats:
    """
    Compute REAL weekly stats when trades_df is provided.
    Fallback to approximate stats if trades_df is empty.

    markets_df → open_interest, active_markets
    trades_df  → weekly_notional_volume, weekly_transactions
    """

    # No markets → zero everything
    if markets_df is None or markets_df.empty:
        return ExchangeStats(
            name="Kalshi",
            weekly_notional_volume=0.0,
            active_markets=0,
            weekly_transactions=0,
            open_interest=0.0,
        )

    # ----- Active markets -----
    active_markets = len(markets_df)

    # ----- Open interest -----
    if "open_interest" in markets_df.columns:
        open_interest = float(markets_df["open_interest"].fillna(0).sum())
    else:
        open_interest = 0.0

    # Default values until trades override them
    weekly_transactions = 0
    weekly_notional = 0.0

    # ================================================================
    #  CASE 1: REAL weekly stats using trades_df (THE GOOD CASE)
    # ================================================================
    if trades_df is not None and not trades_df.empty:

        # Weekly transactions = total contract count
        if "count" in trades_df.columns:
            weekly_transactions = int(trades_df["count"].fillna(0).sum())
        else:
            # Fallback: treat each row as one trade
            weekly_transactions = len(trades_df)

        # Weekly notional = SUM(price * count)
        # price is in cents → convert to dollars
        if "price" in trades_df.columns and "count" in trades_df.columns:
            price_cents = trades_df["price"].fillna(0).astype(float)
            size = trades_df["count"].fillna(0).astype(float)
            weekly_notional = float((price_cents / 100.0 * size).sum())

        else:
            # Fallback estimate: use any *_price_dollars column
            price_cols = [c for c in trades_df.columns if c.endswith("_price_dollars")]
            if price_cols and "count" in trades_df.columns:
                price_dollars = trades_df[price_cols[0]].fillna(0).astype(float)
                size = trades_df["count"].fillna(0).astype(float)
                weekly_notional = float((price_dollars * size).sum())

        return ExchangeStats(
            name="Kalshi",
            weekly_notional_volume=weekly_notional,
            active_markets=active_markets,
            weekly_transactions=weekly_transactions,
            open_interest=open_interest,
        )

    # ================================================================
    #  CASE 2: No trades_df → fallback approximation using markets_df
    # ================================================================
    if "volume_24h" in markets_df.columns:
        v24 = markets_df["volume_24h"].fillna(0).astype(float)
        weekly_transactions = int(v24.sum() * 7)

        if "last_price_dollars" in markets_df.columns:
            price = markets_df["last_price_dollars"].fillna(0).astype(float)
            weekly_notional = float((v24 * price * 7).sum())
        else:
            weekly_notional = float(v24.sum() * 7)

    elif "volume" in markets_df.columns:
        vol = markets_df["volume"].fillna(0).astype(float)
        weekly_transactions = int(vol.sum())

        if "last_price_dollars" in markets_df.columns:
            price = markets_df["last_price_dollars"].fillna(0).astype(float)
            weekly_notional = float((vol * price).sum())
        else:
            weekly_notional = float(vol.sum())

    return ExchangeStats(
        name="Kalshi",
        weekly_notional_volume=weekly_notional,
        active_markets=active_markets,
        weekly_transactions=weekly_transactions,
        open_interest=open_interest,
    )

def compute_polymarket_stats(
    gamma_df: Optional[pd.DataFrame] = None,
    display_df: Optional[pd.DataFrame] = None,
    trades_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
) -> ExchangeStats:
    """
    Polymarket stats:
    - active_markets: count of markets (Gamma rows) if provided, else count unique events in display_df
    - weekly_notional_volume: REAL from trades_df when provided; otherwise proxy from 24h volume * 7
    - weekly_transactions: REAL from trades_df when provided; otherwise 0
    - open_interest: unknown for now -> 0 (until we ingest OI equivalent)
    """

    # No data → zero
    if (gamma_df is None or gamma_df.empty) and (display_df is None or display_df.empty):
        return ExchangeStats(
            name="Polymarket",
            weekly_notional_volume=0.0,
            active_markets=0,
            weekly_transactions=0,
            open_interest=0.0,
        )

    # ----- Active markets -----
    if gamma_df is not None and not gamma_df.empty:
        active_markets = len(gamma_df)
    else:
        if display_df is not None and "event_ticker" in display_df.columns:
            active_markets = int(display_df["event_ticker"].nunique())
        else:
            active_markets = 0 if display_df is None else len(display_df)
        
    # ----- Open interest ----- 
    open_interest = 0.0
    if oi_df is not None and not oi_df.empty:
        # If API provides a GLOBAL row, prefer that
        if "market" in oi_df.columns and "value" in oi_df.columns:
            global_row = oi_df[oi_df["market"] == "GLOBAL"]
            if not global_row.empty:
                open_interest = float(global_row["value"].fillna(0).iloc[0])
            else:
                open_interest = float(oi_df["value"].fillna(0).astype(float).sum())

    # ----- Real weekly stats from trades_df (preferred) -----
    weekly_transactions = 0
    weekly_notional = 0.0

    if trades_df is not None and not trades_df.empty:
        weekly_transactions = int(len(trades_df))

        if "price" in trades_df.columns and "size" in trades_df.columns:
            p = trades_df["price"].fillna(0).astype(float)
            s = trades_df["size"].fillna(0).astype(float)
            weekly_notional = float((p * s).sum())
        else:
            weekly_notional = 0.0
            
        return ExchangeStats(
            name="Polymarket",
            weekly_notional_volume=weekly_notional,
            active_markets=active_markets,
            weekly_transactions=weekly_transactions,
            open_interest=open_interest,
        )

    # ----- Proxy weekly stats (fallback) -----
    # If no trades yet, approximate 7d notional as 24h volume * 7
    if gamma_df is not None and not gamma_df.empty:
        if "volume24hrClob" in gamma_df.columns:
            v24 = gamma_df["volume24hrClob"].fillna(0).astype(float)
            weekly_notional = float(v24.sum() * 7)
        elif "volume24hr" in gamma_df.columns:
            v24 = gamma_df["volume24hr"].fillna(0).astype(float)
            weekly_notional = float(v24.sum() * 7)
    elif display_df is not None and not display_df.empty and "volume_24h" in display_df.columns:
        # display_df repeats volume per outcome row; avoid double counting by grouping events
        if "event_ticker" in display_df.columns:
            weekly_notional = float(display_df.groupby("event_ticker")["volume_24h"].max().sum() * 7)
        else:
            weekly_notional = float(display_df["volume_24h"].fillna(0).astype(float).sum() * 7)

    return ExchangeStats(
        name="Polymarket",
        weekly_notional_volume=weekly_notional,
        active_markets=active_markets,
        weekly_transactions=weekly_transactions,
        open_interest=open_interest,
    )

# ---------------------------
# Public API
# ---------------------------

def get_top_level_stats(
    kalshi_markets_df: Optional[pd.DataFrame] = None,
    kalshi_trades_df: Optional[pd.DataFrame] = None,
    polymarket_gamma_df: Optional[pd.DataFrame] = None,
    polymarket_display_df: Optional[pd.DataFrame] = None,
    polymarket_trades_df: Optional[pd.DataFrame] = None,
    polymarket_oi_df: Optional[pd.DataFrame] = None,
) -> TopLevelStats:

    kalshi_stats = compute_kalshi_stats(
        markets_df=kalshi_markets_df,
        trades_df=kalshi_trades_df,
    )

    polymarket_stats = None
    if (polymarket_gamma_df is not None and not polymarket_gamma_df.empty) or (
        polymarket_display_df is not None and not polymarket_display_df.empty
    ):
        polymarket_stats = compute_polymarket_stats(
            gamma_df=polymarket_gamma_df,
            display_df=polymarket_display_df,
            trades_df=polymarket_trades_df,
            oi_df=polymarket_oi_df,
        )

    return TopLevelStats(
        kalshi=kalshi_stats,
        polymarket=polymarket_stats,
    )