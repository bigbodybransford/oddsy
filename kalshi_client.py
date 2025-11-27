import streamlit as st
import pandas as pd
import requests

url = "https://api.elections.kalshi.com/trade-api/v2/markets"

response = requests.get(url)
data = response.json()

# print(type(data))
# print(data.keys())

markets = data.get("markets", [])
df = pd.json_normalize(markets)
print(df.head())
print(df.columns)