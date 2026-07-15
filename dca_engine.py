# -*- coding: utf-8 -*-
"""
dca_engine.py
=============
定期定額 (DCA) 回測的「純計算」核心模組。

本模組刻意「不依賴 Streamlit / yfinance」，只吃一條 pandas 價格序列 (Adj Close)，
方便單元測試與重複使用。主要負責三件事：

1. 依「投資頻率」產生扣款排程日 (schedule dates)。
2. 交易日順延：遇假日／非交易日，自動往後找到下一個有效交易日買入。
3. 動態金額狀態機：依「投資第幾年」切換扣款金額；若超過陣列長度則沿用最後一個值。
4. 績效指標：總投入、累積股數、期末市值、總報酬率，以及用 XIRR 計算的年化報酬率。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta


# =============================================================================
#  資料結構
# =============================================================================
@dataclass
class DcaResult:
    """單一計畫的回測結果容器。"""
    timeseries: pd.DataFrame            # index=交易日, 欄位: price / invested_cum / shares_cum / market_value
    buys: List[Tuple[pd.Timestamp, float, float, float]]  # (買入日, 金額, 股數, 當日價格)
    metrics: dict = field(default_factory=dict)           # 績效總覽


# =============================================================================
#  1. 扣款排程日產生器
# =============================================================================
def generate_schedule_dates(start: pd.Timestamp,
                            end: pd.Timestamp,
                            frequency: str) -> pd.DatetimeIndex:
    """
    產生「理論上的」扣款日期（尚未考慮假日）。

    - monthly  : 以 start 的「日」為錨點，每隔 1 個月扣一次（例如每月 5 號）。
    - biweekly : 每 14 天扣一次。
    - weekly   : 每 7 天扣一次。

    之所以用 DateOffset(months=1) 而非固定 30 天，是為了讓「每月」真正落在
    同一個日子（避免日期漂移），這也讓後面「投資第幾年」的計算更直觀。
    """
    freq_map = {
        "monthly":  pd.DateOffset(months=1),
        "biweekly": pd.Timedelta(days=14),
        "weekly":   pd.Timedelta(days=7),
    }
    if frequency not in freq_map:
        raise ValueError(f"不支援的投資頻率: {frequency}")
    return pd.date_range(start=start, end=end, freq=freq_map[frequency])


# =============================================================================
#  2. 動態金額狀態機
# =============================================================================
def resolve_amount(schedule: List[float],
                   start: pd.Timestamp,
                   contribution_date: pd.Timestamp) -> float:
    """
    根據「距離起始日已過的完整年數」決定本次扣款金額。

    邏輯（動態金額狀態機）：
      - relativedelta(a, b).years 會回傳兩個日期相差的「完整年數」。
        例如 2020-06-01 → 2021-05-31 只算 0 年；到 2021-06-01 才算滿 1 年。
      - year_index = 完整年數，對應到 schedule 的索引：
            第 1 年(未滿 1 年) -> schedule[0]
            第 2 年            -> schedule[1] ...
      - 若 year_index 超出陣列長度（回測年數 > 輸入的階梯數），
        則 min() 夾住索引，沿用「最後一個」金額（Step-up 的常態行為）。
    """
    year_index = relativedelta(contribution_date, start).years
    idx = min(year_index, len(schedule) - 1)   # 超過陣列 -> 沿用最後一格
    return float(schedule[idx])


# =============================================================================
#  3. 交易日順延 + 主回測迴圈
# =============================================================================
def run_dca(price: pd.Series,
            schedule: List[float],
            start: pd.Timestamp,
            end: pd.Timestamp,
            frequency: str = "monthly") -> DcaResult:
    """
    執行單一計畫的 DCA 回測。

    參數
    ----
    price     : pd.Series，index 為交易日 (DatetimeIndex)，值為調整後收盤價。
    schedule  : 階梯金額陣列，如 [3000, 5000, 8000]。
    start/end : 回測起訖日。
    frequency : monthly / biweekly / weekly。
    """
    # 只保留回測區間內、且有價格的交易日
    price = price[(price.index >= start) & (price.index <= end)].dropna().sort_index()
    if price.empty:
        raise ValueError("回測區間內沒有任何有效價格資料。")

    trading_days = price.index
    schedule_dates = generate_schedule_dates(start, end, frequency)

    buys: List[Tuple[pd.Timestamp, float, float, float]] = []

    for sched_d in schedule_dates:
        # -------- 交易日順延邏輯 --------
        # searchsorted(side="left") 會回傳「第一個 >= sched_d」的位置，
        # 這正好等於「遇到假日就往後找下一個有效交易日」的語意。
        pos = trading_days.searchsorted(sched_d, side="left")
        if pos >= len(trading_days):
            # 排程日超過了資料範圍（例如最後一期落在資料結束後），跳過不買。
            break
        buy_day = trading_days[pos]

        # -------- 動態金額 --------
        # 用「原始排程日」而非順延後的買入日來判斷年份，
        # 避免順延幾天恰好跨年造成金額提早/延後切換。
        amount = resolve_amount(schedule, start, sched_d)

        buy_price = float(price.loc[buy_day])
        shares = amount / buy_price
        buys.append((buy_day, amount, shares, buy_price))

    if not buys:
        raise ValueError("在此區間與頻率下沒有產生任何買入交易，請調整參數。")

    # -------- 建立每日累積時序（本金 / 股數 / 市值）--------
    df = pd.DataFrame(index=trading_days)
    df["price"] = price

    daily_amt = pd.Series(0.0, index=trading_days)
    daily_sh = pd.Series(0.0, index=trading_days)
    for bd, amt, sh, _ in buys:
        # 用 += 是因為順延後可能有多筆排程落在同一交易日（例如週頻遇連假）
        daily_amt.loc[bd] += amt
        daily_sh.loc[bd] += sh

    df["invested_cum"] = daily_amt.cumsum()          # 累積投入本金
    df["shares_cum"] = daily_sh.cumsum()             # 累積持有股數
    df["market_value"] = df["shares_cum"] * df["price"]  # 每日市值

    # 從「第一次買入」之後才有意義，前面的空窗裁掉，讓圖表更乾淨
    df = df[df.index >= buys[0][0]]

    metrics = _compute_metrics(buys, df)
    return DcaResult(timeseries=df, buys=buys, metrics=metrics)


# =============================================================================
#  4. 績效指標
# =============================================================================
def _compute_metrics(buys, df) -> dict:
    total_invested = sum(b[1] for b in buys)
    total_shares = sum(b[2] for b in buys)
    final_price = float(df["price"].iloc[-1])
    final_value = total_shares * final_price
    total_return = (final_value - total_invested) / total_invested if total_invested else np.nan

    # ---- 年化報酬率 (XIRR) ----
    # 每一筆扣款都是一筆「現金流出」(負值)，發生在其買入當日；
    # 期末市值視為一筆「現金流入」(正值)，發生在最後一個交易日。
    cashflows = [(bd, -amt) for bd, amt, _, _ in buys]
    cashflows.append((df.index[-1], final_value))
    annualized = xirr(cashflows)

    return {
        "total_invested": total_invested,
        "total_shares": total_shares,
        "final_price": final_price,
        "final_value": final_value,
        "total_return": total_return,
        "annualized_return": annualized,
        "start_date": df.index[0],
        "end_date": df.index[-1],
    }


# =============================================================================
#  XIRR（不定期現金流的內部報酬率）
# =============================================================================
def _xnpv(rate: float, cashflows: List[Tuple[pd.Timestamp, float]]) -> float:
    """
    給定折現率 rate，計算現金流的淨現值 (以「年」為時間單位)。

    XNPV = Σ  CF_i / (1 + rate) ^ (days_i / 365)
    其中 days_i = 該筆現金流距離「最早一筆現金流」的天數。
    """
    t0 = min(t for t, _ in cashflows)
    return sum(cf / (1.0 + rate) ** ((t - t0).days / 365.0) for t, cf in cashflows)


def xirr(cashflows: List[Tuple[pd.Timestamp, float]]) -> float:
    """
    以「二分逼近法 (bisection)」求解使 XNPV=0 的年化報酬率。

    為什麼用二分法而不是 numpy_financial.irr？
      - numpy_financial.irr 假設「每一期間隔相等」，但我們的買入日因為
        交易日順延與月份長度不同，間隔並不固定。
      - XIRR 直接把「實際天數」納入折現，才是全球市場通用、且對不規則
        扣款日最精確的年化算法。

    對典型「先流出、後流入」的投資現金流而言，XNPV 相對 rate 單調遞減，
    因此二分法穩定且必收斂；找不到變號區間時回傳 NaN。
    """
    amounts = [cf for _, cf in cashflows]
    # 必須同時存在正、負現金流，IRR 才有意義
    if not (min(amounts) < 0 < max(amounts)):
        return float("nan")

    low, high = -0.9999, 1.0
    f_low = _xnpv(low, cashflows)

    # 動態擴張上界，直到 XNPV 由正轉負（找到變號區間）
    f_high = _xnpv(high, cashflows)
    expand = 0
    while f_low * f_high > 0 and expand < 100:
        high *= 1.5
        f_high = _xnpv(high, cashflows)
        expand += 1
    if f_low * f_high > 0:
        return float("nan")  # 無法括住根，放棄

    # 二分逼近
    for _ in range(200):
        mid = (low + high) / 2.0
        f_mid = _xnpv(mid, cashflows)
        if abs(f_mid) < 1e-8:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2.0
