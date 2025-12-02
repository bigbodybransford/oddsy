# Oddsy — Prediction Market Terminal (MVP)
Oddsy is an early-stage prediction market terminal designed to aggregate and compare markets across exchanges such as Kalshi and Polymarket. The MVP focuses on core data ingestion, normalization, and an interactive UI for exploring markets in real time.

---

## Current Features
- Fetch live Kalshi markets and trades using public endpoints  
- Normalize and clean market and trades data (prices, volumes, categories)  
- Convert price to probability  
- Filter by categories (Sports, Crypto, Politics, etc.)  
- Filter by market status (active or closed)  
- Minimum-volume filtering  
- Sort by volume, last traded percentage, or close time  
- Card-based Streamlit UI  
- Early platform tagging for multi-exchange support

---

## Tech Stack
- Python  
- Streamlit  
- Pandas  
- Requests  
- Kalshi API  

---

### Run the App
streamlit run app.py

---

#### Roadmap
- Add authenticated Kalshi API endpoints
- Integrate Polymarket API
- Create unified market schema across exchanges
- Add odds comparison and spread visualization
- Add arbitrage surface detection
- Build watchlists, search, and alerts
- Add historical charts and time-series data
- Portfolio tracking

---

#### Project Status
Early MVP. Actively in development with ongoing daily/weekly iterations. 