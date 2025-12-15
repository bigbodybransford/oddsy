import streamlit as st
import pandas as pd
import numpy as np
import requests
import os
import datetime
import base64
import re

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv
from oddsy_services.stats_service import get_top_level_stats
from ui.components.stats_bar import render_stats_bar

from oddsy_services.kalshi_client import fetch_kalshi_markets, fetch_kalshi_trades_last_week
from oddsy_services.polymarket_client import fetch_polymarket_markets, fetch_polymarket_trades_last_7d, fetch_polymarket_open_interest
from oddsy_services.market_transform import build_kalshi_display_df, build_polymarket_display_df


load_dotenv()

st.set_page_config(page_title="Prediction Markets MVP", layout="wide")
st.title("Prediction Market Terminal (Kalshi - Public Endpoint MVP)")
st.write("Data from Kalshi elections API.")

platform_choice = st.radio(
    "Platform",
    ["Kalshi", "Polymarket", "Both"],
    horizontal=True,
    index=0,
    key="platform_choice",
)

if st.button("Refresh Data"):
    choice = st.session_state.get("platform_choice", "Kalshi")
    df_list = []

    # --- Kalshi ---
    if choice in ("Kalshi", "Both"):
        km = fetch_kalshi_markets(status="open", max_pages=5, page_limit=500)
        kt = fetch_kalshi_trades_last_week(max_pages=5)

        st.session_state["kalshi_markets_df"] = km
        st.session_state["kalshi_trades_df"] = kt

        k_display = build_kalshi_display_df(km)
        df_list.append(k_display)
    else:
        st.session_state["kalshi_markets_df"] = None
        st.session_state["kalshi_trades_df"] = None

    # --- Polymarket ---
    if choice in ("Polymarket", "Both"):
        gamma_df, books_by_token = fetch_polymarket_markets(limit=200, max_pages=5)
        
        pm_trades_df = fetch_polymarket_trades_last_7d(limit=500, max_pages=50)
        pm_oi_df = fetch_polymarket_open_interest()
        
        # st.write("DEBUG: pm_trades_df rows (raw) =", len(pm_trades_df))
        # if not pm_trades_df.empty and "timestamp" in pm_trades_df.columns:
        #     st.write("DEBUG: pm_trades_df ts min/max =", int(pm_trades_df["timestamp"].min()), int(pm_trades_df["timestamp"].max()))
        
        st.session_state["pm_gamma_df"] = gamma_df
        st.session_state["pm_books_by_token"] = books_by_token
        st.session_state["pm_trades_df"] = pm_trades_df
        st.session_state["pm_oi_df"] = pm_oi_df

        pm_display = build_polymarket_display_df(gamma_df, books_by_token)
        df_list.append(pm_display)
    else:
        st.session_state["pm_gamma_df"] = None
        st.session_state["pm_books_by_token"] = None
        st.session_state["pm_trades_df"] = None
        st.session_state["pm_oi_df"] = None

    # unified df for UI rendering
    st.session_state["df_display"] = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()

    st.success("Fetched latest markets!")

df_display = st.session_state.get("df_display")
kalshi_markets_df = st.session_state.get("kalshi_markets_df")
kalshi_trades_df = st.session_state.get("kalshi_trades_df")

if df_display is None or df_display.empty:
    st.info("Click 'Refresh Data' to load markets.")
else:
    # ---- Debug counts (keep while iterating) ----
    # st.write(
    #     "DEBUG: df_display rows =", 0 if df_display is None else len(df_display),
    #     "| Kalshi trades rows =", 0 if kalshi_trades_df is None else len(kalshi_trades_df)
    # )

    # ---- Top-level stats bar (already working) ----
    choice = st.session_state.get("platform_choice", "Kalshi")

    df_display = st.session_state.get("df_display")
    kalshi_markets_df = st.session_state.get("kalshi_markets_df")
    kalshi_trades_df = st.session_state.get("kalshi_trades_df")
    pm_gamma_df = st.session_state.get("pm_gamma_df")
    pm_trades_df = st.session_state.get("pm_trades_df")
    pm_oi_df = st.session_state.get("pm_oi_df")

    # For Polymarket-only selection, pass empty Kalshi so TopLevelStats.kalshi still exists
    if choice == "Polymarket":
        empty_k = pd.DataFrame()
        top_level_stats = get_top_level_stats(
            kalshi_markets_df=empty_k,
            kalshi_trades_df=None,
            polymarket_gamma_df=pm_gamma_df,
            polymarket_display_df=df_display,
            polymarket_trades_df=pm_trades_df,
            polymarket_oi_df=pm_oi_df,
        )
    elif choice == "Kalshi":
        top_level_stats = get_top_level_stats(
            kalshi_markets_df=kalshi_markets_df,
            kalshi_trades_df=kalshi_trades_df,
        )
    else:  # Both (we can keep it simple for now)
        top_level_stats = get_top_level_stats(
            kalshi_markets_df=kalshi_markets_df,
            kalshi_trades_df=kalshi_trades_df,
            polymarket_gamma_df=pm_gamma_df,
            polymarket_display_df=df_display,
            polymarket_trades_df=pm_trades_df,
            polymarket_oi_df=pm_oi_df,
        )

    render_stats_bar(top_level_stats, mode=choice)
    
    st.markdown("---")

    df_display = st.session_state.get("df_display")

    # ---- Sort by 24h volume (Top Markets by Volume) ----
    if "volume_24h" in df_display.columns:
        df_display = df_display.sort_values("volume_24h", ascending=False)
    elif "volume" in df_display.columns:
        df_display = df_display.sort_values("volume", ascending=False)

    # ---- Build event-level groups (group by event_ticker) ----
    if "event_ticker" not in df_display.columns:
        # Fallback: treat each market as its own event
        df_display["event_ticker"] = df_display.get("ticker")

    events = []
    for event_id, group in df_display.groupby("event_ticker"):
        # Sort markets in this event by implied YES probability (desc)
        group_sorted = group.sort_values("implied_yes_prob", ascending=False)

        first = group_sorted.iloc[0]

        event_title = first.get("title") or str(event_id)
        category = first.get("category")
        status = first.get("status")
        platform = first.get("platform", "Unknown")

        total_vol_24h = (
            group_sorted["volume_24h"].fillna(0).sum()
            if "volume_24h" in group_sorted.columns
            else 0
        )
        total_oi = (
            group_sorted["open_interest"].fillna(0).sum()
            if "open_interest" in group_sorted.columns
            else None
        )
        event_close = first.get("close_time")

        events.append(
            {
                "event_ticker": event_id,
                "title": event_title,
                "category": category,
                "status": status,
                "volume_24h": total_vol_24h,
                "open_interest": total_oi,
                "close_time": event_close,
                "platform": platform,
                "markets": group_sorted,
            }
        )

    # Sort events by total 24h volume (Top Events by Volume)
    events_sorted = sorted(
        events,
        key=lambda e: e["volume_24h"] if e["volume_24h"] is not None else 0,
        reverse=True,
    )

    st.subheader("Top Events by Volume")
    st.caption(
        "Grouped by event; top 2 outcomes shown inline, remaining options in an expander."
    )
    st.write(f"Showing {len(events_sorted)} events")

    # Optional: raw markets table for debugging
    show_table = st.checkbox("Show raw markets table", value=False)
    st.write("Platforms in df_display:", sorted(df_display["platform"].dropna().unique().tolist()))

    if show_table:
        st.dataframe(df_display.reset_index(drop=True), use_container_width=True)
    else:
        # ---- Event card grid layout ----
        n_cols = 2  # 2 event cards per row
        for row_start in range(0, len(events_sorted), n_cols):
            row_events = events_sorted[row_start : row_start + n_cols]
            cols_streamlit = st.columns(len(row_events))

            for offset, (col, event) in enumerate(zip(cols_streamlit, row_events)):
                rank = row_start + offset + 1
                markets = event["markets"]
                markets_sorted = markets.sort_values(
                    "implied_yes_prob", ascending=False
                )

                top_two = markets_sorted.head(2)
                rest = markets_sorted.iloc[2:]
                total_markets = len(markets_sorted)

                with col:
                    with st.container(border=True):
                        # Rank badge
                        st.markdown(
                            f"<div style='font-size: 0.85rem; "
                            f"background-color: #f5a623; color: white; "
                            f"display: inline-block; padding: 0.2rem 0.6rem; "
                            f"border-radius: 999px; font-weight: 600;'>"
                            f"{rank}</div>",
                            unsafe_allow_html=True,
                        )

                        # Header row: event title + platform pill
                        title = event.get("title", f"Event {event['event_ticker']}")
                        platform = event.get("platform", "Unknown")
                        st.markdown(
                            f"<div style='display:flex; justify-content:space-between; "
                            f"align-items:center; margin-top:0.5rem;'>"
                            f"<div style='font-weight:600; font-size:1rem;'>{title}</div>"
                            f"<div style='background-color:#1a73e8; color:white; "
                            f"padding:0.15rem 0.6rem; border-radius:999px; "
                            f"font-size:0.75rem; font-weight:500;'>{platform}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                        # Chips: category + status
                        category = event.get("category")
                        status = event.get("status")

                        chips_html = "<div style='margin-top:0.4rem; display:flex; gap:0.4rem;'>"
                        if category:
                            chips_html += (
                                "<div style='font-size:0.7rem; padding:0.1rem 0.4rem; "
                                "border-radius:999px; background-color:#f2f2f2;'>"
                                f"{category}</div>"
                            )
                        if status:
                            color = "#e6f4ea" if str(status).lower() == "open" else "#fce8e6"
                            text_color = "#137333" if str(status).lower() == "open" else "#c5221f"
                            chips_html += (
                                f"<div style='font-size:0.7rem; padding:0.1rem 0.4rem; "
                                f"border-radius:999px; background-color:{color}; "
                                f"color:{text_color};'>"
                                f"{status}</div>"
                            )
                        chips_html += "</div>"

                        st.markdown(chips_html, unsafe_allow_html=True)

                        st.markdown("---")

                        def outcome_label(row):
                            """
                            Choose a short, outcome-specific label.
                            """
                            
                            # 0) If we successfully parsed a name from the title, use that first
                            from_title = row.get("option_name_from_title")
                            if isinstance(from_title, str) and from_title.strip():
                                return from_title.strip()
                            
                            # Readable label for a single outcome within an event.

                            # Priority:
                            # 1) yes_sub_title, cleaned (this is where things like ':: Democratic' live)
                            # 2) ticker suffix (after the last '-'), as a fallback
                            

                            # 1) Prefer yes_sub_title if it’s there
                            raw = row.get("yes_sub_title")
                            label = ""
                            if isinstance(raw, str):
                                label = raw.strip()

                            # 2) Fallback to ticker suffix if we have nothing
                            if not label:
                                ticker = str(row.get("ticker", "")).strip()
                                if "-" in ticker:
                                    label = ticker.split("-")[-1].strip()
                                else:
                                    label = ticker

                            # 3) Clean Kalshi’s "::" prefix if present
                            if label.startswith("::"):
                                # remove all leading colons + trim spaces
                                label = label.lstrip(":").strip()

                            # Final fallback
                            if not label:
                                label = "(unknown)"

                            return label

                        # ---- Top 2 outcomes (by YES prob) ----
                        st.markdown(
                            "<div style='font-size:0.8rem; font-weight:600; "
                            "margin-bottom:0.3rem;'>Top outcomes (YES probability)"
                            "</div>",
                            unsafe_allow_html=True,
                        )

                        for _, m in top_two.iterrows():
                            label = outcome_label(m)
                            prob = m.get("implied_yes_prob", None)
                            prob_text = "n/a" if prob is None else f"{prob:.1f}%"

                            st.markdown(
                                "<div style='display:flex; justify-content:space-between; "
                                "align-items:center; padding:0.35rem 0.6rem; "
                                "border-radius:0.6rem; background-color:#f8fafc; "
                                "margin-bottom:0.3rem;'>"
                                f"<span style='font-size:0.85rem;'>{label}</span>"
                                f"<span style='font-weight:600;'>{prob_text}</span>"
                                "</div>",
                                unsafe_allow_html=True,
                            )

                        # ---- Remaining outcomes in expander ----
                        if total_markets > 2:
                            with st.expander(f"View all {total_markets} options"):
                                pills_cols = st.columns(3)
                                for idx2, (_, m2) in enumerate(markets_sorted.iterrows()):
                                    label2 = outcome_label(m2)
                                    prob2 = m2.get("implied_yes_prob", None)
                                    prob_text2 = (
                                        "n/a" if prob2 is None else f"{prob2:.1f}%"
                                    )

                                    pill_col = pills_cols[idx2 % 3]
                                    with pill_col:
                                        st.markdown(
                                            "<div style='padding:0.25rem 0.5rem; "
                                            "border-radius:999px; background-color:#f1f5f9; "
                                            "margin-bottom:0.25rem; font-size:0.75rem; "
                                            "display:flex; justify-content:space-between;'>"
                                            f"<span>{label2}</span>"
                                            f"<span style='font-weight:600;'>{prob_text2}</span>"
                                            "</div>",
                                            unsafe_allow_html=True,
                                        )

                        # ---- Event-level stats row ----
                        vol_24h = event.get("volume_24h")
                        oi = event.get("open_interest")
                        close_time = event.get("close_time", "N/A")

                        bottom_html = (
                            "<div style='display:flex; justify-content:space-between; "
                            "margin-top:0.6rem; font-size:0.8rem;'>"
                        )

                        bottom_html += (
                            "<div>"
                            "<div style='color:#6b6b6b; text-transform:uppercase; "
                            "font-size:0.7rem;'>24h Volume</div>"
                            f"<div style='font-weight:600;'>{vol_24h}</div>"
                            "</div>"
                        )

                        bottom_html += (
                            "<div>"
                            "<div style='color:#6b6b6b; text-transform:uppercase; "
                            "font-size:0.7rem;'>Open Int.</div>"
                            f"<div style='font-weight:600;'>{oi}</div>"
                            "</div>"
                        )

                        bottom_html += (
                            "<div>"
                            "<div style='color:#6b6b6b; text-transform:uppercase; "
                            "font-size:0.7rem;'>Ends</div>"
                            f"<div style='font-weight:600;'>{close_time}</div>"
                            "</div>"
                        )

                        bottom_html += "</div>"

                        st.markdown(bottom_html, unsafe_allow_html=True)