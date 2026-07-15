# -*- coding: utf-8 -*-
"""
data_fetcher.py
===============
負責向 yfinance 取得「全球市場」的歷史調整後收盤價 (Adj Close)。

設計重點：
- 支援全球代碼：US(AAPL, VOO)、台股(2330.TW)、倫敦(VWRA.L)、港股(0700.HK) 等。
- 完整的錯誤捕捉：代碼錯誤、無資料、網路失敗都轉成清楚的 ValueError 訊息，
  交由上層 (app.py) 以 st.error 呈現防呆提示。
- 相容新版 yfinance 的 MultiIndex 欄位格式。
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf


def fetch_adj_close(ticker: str,
                    start: str | pd.Timestamp,
                    end: str | pd.Timestamp) -> pd.Series:
    """
    取得單一代碼在 [start, end] 區間的「調整後收盤價」序列。

    回傳：pd.Series（index=交易日, name=ticker）。
    失敗時丟出帶有中文說明的 ValueError。
    """
    ticker = (ticker or "").strip()
    if not ticker:
        raise ValueError("代碼不可為空白。")

    try:
        # auto_adjust=False 才會保留獨立的 'Adj Close' 欄位（新版預設會把它折進 Close）。
        df = yf.download(
            ticker,
            start=start,
            end=end,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as e:  # 網路 / 解析層級的錯誤
        raise ValueError(f"抓取 {ticker} 時發生連線或解析錯誤：{e}") from e

    if df is None or df.empty:
        raise ValueError(
            f"找不到 {ticker} 的資料。請確認代碼是否正確"
            f"（美股如 AAPL、台股需加 .TW 如 2330.TW、倫敦需加 .L 如 VWRA.L）。"
        )

    # --- 相容 MultiIndex 欄位（新版 yfinance 即使單一代碼也可能回傳雙層欄位）---
    if isinstance(df.columns, pd.MultiIndex):
        # 取第一層欄名（'Adj Close' / 'Close' ...）
        df.columns = df.columns.get_level_values(0)

    # 優先用 Adj Close，退而求其次用 Close
    if "Adj Close" in df.columns:
        s = df["Adj Close"]
    elif "Close" in df.columns:
        s = df["Close"]
    else:
        raise ValueError(f"{ticker} 的回傳資料缺少收盤價欄位。")

    # 若仍是 DataFrame（極少數情況），取第一欄
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]

    s = s.dropna()
    s.index = pd.to_datetime(s.index)
    s.name = ticker

    if s.empty:
        raise ValueError(f"{ticker} 在此區間內沒有有效的價格資料。")
    return s
