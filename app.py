# -*- coding: utf-8 -*-
"""
app.py — 全球市場「定期定額 (DCA) 策略回測工具」
=================================================
特色：
- 多情境對比（每組計畫可設不同標的 / 不同階梯金額）。
- 階梯式動態扣款 (Step-up DCA)。
- 電腦版 + 手機版皆有良好體驗（Sidebar 收納參數、CSS 響應式微調、Plotly autosize）。

模組化：
- 資料抓取 -> data_fetcher.py
- 回測邏輯 -> dca_engine.py
- UI 呈現   -> 本檔 app.py

執行：  streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_fetcher import fetch_adj_close
from dca_engine import run_dca


# =============================================================================
#  頁面設定 + 響應式 CSS
# =============================================================================
st.set_page_config(
    page_title="全球 DCA 定期定額回測",
    page_icon="📈",
    layout="wide",                 # 寬版：手機版主畫面才能完整塞下圖表
    initial_sidebar_state="expanded",
)

# ---- 自定義 CSS：針對行動裝置優化 Padding 與 Font-size ----
# 說明：
#   - 縮小主容器左右內距，讓窄螢幕能用滿寬度、圖表不溢出。
#   - 用 @media 查詢在 <= 640px（手機）時縮小標題與內距。
#   - 讓 Plotly 圖表容器 100% 寬、可橫向捲動避免爆版。
st.markdown(
    """
    <style>
    /* 主容器內距（桌機） */
    .block-container { padding-top: 2.2rem; padding-bottom: 2rem;
                       padding-left: 2rem; padding-right: 2rem; max-width: 1400px; }

    /* 讓 Plotly 圖不會超出容器；表格可橫向捲動 */
    .stPlotlyChart { width: 100% !important; }
    [data-testid="stDataFrame"] { overflow-x: auto; }

    /* 計畫顏色標籤 */
    .plan-chip { display:inline-block; padding:2px 10px; border-radius:12px;
                 color:#fff; font-size:0.8rem; font-weight:600; margin-bottom:4px; }

    /* ------- 手機版 (<=640px) 微調 ------- */
    @media (max-width: 640px) {
        .block-container { padding-left: 0.7rem; padding-right: 0.7rem;
                           padding-top: 3rem; }
        h1 { font-size: 1.35rem !important; }
        h2 { font-size: 1.1rem !important; }
        h3 { font-size: 1rem !important; }
        /* 指標數字在小螢幕縮一點，避免換行爆版 */
        [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
        [data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
        [data-testid="stDataFrame"] { font-size: 0.8rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 每組計畫的固定配色（顏色標籤 + 圖表線色一致）
PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2"]


# =============================================================================
#  快取包裝：避免重複打 API
# =============================================================================
@st.cache_data(show_spinner=False, ttl=3600)
def cached_fetch(ticker: str, start: str, end: str) -> pd.Series:
    return fetch_adj_close(ticker, start, end)


def parse_schedule(text: str) -> list[float]:
    """把 '3000, 5000, 8000' 解析為 [3000, 5000, 8000]，忽略空白與非法值。"""
    vals = []
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            vals.append(float(part))
        except ValueError:
            raise ValueError(f"金額 '{part}' 不是有效數字。")
    if not vals:
        raise ValueError("請至少輸入一個扣款金額。")
    return vals


def chip(name: str, color: str) -> str:
    return f'<span class="plan-chip" style="background:{color}">{name}</span>'


# =============================================================================
#  UI Rendering —— 側邊欄（參數輸入集中於此，主畫面留給圖表）
# =============================================================================
st.sidebar.title("⚙️ 回測參數")

with st.sidebar:
    st.subheader("① 全域設定")
    c1, c2 = st.columns(2)
    start_date = c1.date_input("起始日", value=pd.Timestamp("2018-01-01")).isoformat()
    end_date = c2.date_input("結束日", value=pd.Timestamp.today().normalize()).isoformat()

    frequency = st.selectbox(
        "扣款頻率",
        options=[("每月", "monthly"), ("每兩週", "biweekly"), ("每週", "weekly")],
        format_func=lambda x: x[0],
    )[1]

    currency = st.text_input("計價符號（顯示用）", value="$",
                             help="僅為顯示；混用不同市場時金額幣別以各標的為準。")

    # 排序設定：預設依「總報酬率」由高到低，讓表現最好的計畫排最前面。
    sort_metric = st.selectbox(
        "績效排序依據",
        options=[("總報酬率", "total_return"),
                 ("年化報酬(IRR)", "annualized_return"),
                 ("期末市值", "final_value")],
        format_func=lambda x: x[0],
    )[1]
    sort_desc = st.radio("排序方向", options=["高 → 低", "低 → 高"],
                         horizontal=True) == "高 → 低"

    st.divider()
    st.subheader("② 計畫（可多組對比）")
    n_plans = st.number_input("計畫數量", min_value=1, max_value=6, value=2, step=1)

    plans = []
    for i in range(int(n_plans)):
        color = PALETTE[i % len(PALETTE)]
        st.markdown(chip(f"計畫 {i+1}", color), unsafe_allow_html=True)
        default_ticker = "VOO" if i == 0 else "AAPL"

        tk = st.text_input("標的代碼", value=default_ticker, key=f"tk{i}",
                           help="AAPL / VOO / 2330.TW / VWRA.L / 0700.HK …")

        # ---- 新增式階梯金額：每一年一格，可按鈕增減 ----
        # 用 session_state 記住「這個計畫有幾年」，才能在重跑後保留使用者加減的結果。
        ny_key = f"nyears_{i}"
        if ny_key not in st.session_state:
            defaults = [5000] if i == 0 else [3000, 5000, 8000]
            st.session_state[ny_key] = len(defaults)
            for y, d in enumerate(defaults):       # 預先塞入各年預設值
                st.session_state[f"amt_{i}_{y}"] = d

        st.caption("階梯金額（逐年）")
        sched_vals = []
        for y in range(st.session_state[ny_key]):
            # 先確保該年欄位有預設值（新加的一年沿用前一年），再建立 widget，避免 value/key 衝突警告
            if f"amt_{i}_{y}" not in st.session_state:
                st.session_state[f"amt_{i}_{y}"] = st.session_state.get(f"amt_{i}_{y-1}", 5000)
            v = st.number_input(f"第 {y+1} 年金額", min_value=0, step=1000,
                                key=f"amt_{i}_{y}")
            sched_vals.append(v)

        ca, cb = st.columns(2)
        if ca.button("＋ 增加一年", key=f"add_{i}", use_container_width=True):
            y = st.session_state[ny_key]
            st.session_state[f"amt_{i}_{y}"] = sched_vals[-1] if sched_vals else 5000
            st.session_state[ny_key] += 1
            st.rerun()
        if cb.button("－ 移除一年", key=f"del_{i}", use_container_width=True,
                     disabled=st.session_state[ny_key] <= 1):
            st.session_state[ny_key] -= 1
            st.rerun()
        st.caption(f"超過 {len(sched_vals)} 年後，將沿用最後一年金額。")

        # 計畫名稱直接採用輸入的股票代碼；若尚未填代碼則暫用「計畫N」。
        display_name = tk.strip().upper() or f"計畫{i+1}"
        plans.append({"name": display_name, "ticker": tk,
                      "sched": sched_vals, "color": color})
        st.markdown("<hr style='margin:6px 0;border:none;border-top:1px dashed #ccc'>",
                    unsafe_allow_html=True)

    run_btn = st.button("🚀 開始回測", type="primary", use_container_width=True)


# =============================================================================
#  主畫面
# =============================================================================
st.title("📈 全球定期定額 (DCA) 回測工具")
st.caption("支援多情境對比與階梯式動態扣款 (Step-up DCA)。手機與電腦皆已響應式優化。")

# 一旦按過「開始回測」，就把狀態記在 session_state。
# 這樣之後勾選「顯示本金」、切換下拉、改幣別等互動造成的重跑，
# 都仍會顯示結果，而不會因為按鈕的 True 只存在一瞬間而讓畫面清空。
if run_btn:
    st.session_state["has_run"] = True

if not st.session_state.get("has_run"):
    st.info("👈 在左側（手機請點左上角 ▸ 展開側邊欄）設定計畫後，按「開始回測」。")
    st.stop()


# ---- 逐一計算每組計畫；單一計畫失敗不影響其他計畫 ----
results = []      # (plan_dict, DcaResult)
for plan in plans:
    try:
        sched = plan["sched"]  # 已是逐年金額陣列（新增式輸入）
        if not sched or sum(sched) <= 0:
            raise ValueError("請至少輸入一個大於 0 的年度金額。")
        price = cached_fetch(plan["ticker"].strip(), start_date, end_date)
        res = run_dca(
            price,
            sched,
            pd.Timestamp(start_date),
            pd.Timestamp(end_date),
            frequency,
        )
        results.append((plan, res))
    except Exception as e:
        st.error(f"【{plan['name']}｜{plan['ticker']}】回測失敗：{e}")

if not results:
    st.warning("沒有任何計畫成功，請檢查代碼或參數。")
    st.stop()

# ---- 依所選指標排序（NaN 一律沉底，不論升冪或降冪）----
def _sort_key(item):
    v = item[1].metrics.get(sort_metric)
    if v is None or pd.isna(v):
        # 降冪時給 -inf、升冪時給 +inf，讓無效值永遠落在最後
        return float("-inf") if sort_desc else float("inf")
    return v

results.sort(key=_sort_key, reverse=sort_desc)


# ------------------------------------------------------------------
#  區塊 A：績效總覽（指標卡 + 對照表格）
# ------------------------------------------------------------------
st.subheader("績效總覽")

def fmt_money(v):   return f"{currency}{v:,.0f}"
def fmt_pct(v):     return "—" if pd.isna(v) else f"{v*100:,.2f}%"

# 指標卡：每列最多 3 張，手機自動換行
cols = st.columns(min(3, len(results)))
for idx, (plan, res) in enumerate(results):
    m = res.metrics
    with cols[idx % len(cols)]:
        st.markdown(chip(plan["name"], plan["color"]), unsafe_allow_html=True)
        st.metric("期末市值", fmt_money(m["final_value"]),
                  delta=fmt_pct(m["total_return"]))
        st.caption(
            f"投入 {fmt_money(m['total_invested'])}｜"
            f"年化(IRR) **{fmt_pct(m['annualized_return'])}**"
        )

# 對照表格（支援手機橫向捲動）
table_rows = []
for plan, res in results:
    m = res.metrics
    table_rows.append({
        "計畫": plan["name"],
        "標的": plan["ticker"],
        "總投入": fmt_money(m["total_invested"]),
        "累積股數": f"{m['total_shares']:,.4f}",
        "期末市值": fmt_money(m["final_value"]),
        "總報酬率": fmt_pct(m["total_return"]),
        "年化報酬(IRR)": fmt_pct(m["annualized_return"]),
    })
st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


# ------------------------------------------------------------------
#  區塊 B：多情境對比（互動式多線圖）
# ------------------------------------------------------------------
st.subheader("市值走勢對比")

def base_layout(fig: go.Figure, height: int = 460):
    """統一的響應式版面：autosize、圖例置頂橫排（手機不擋線）、精簡邊距。"""
    fig.update_layout(
        autosize=True,
        height=height,
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0),
        template="plotly_white",
        xaxis=dict(title=None, rangeslider=dict(visible=False)),
        yaxis=dict(title=None, tickformat=",.0f"),
    )
    return fig

fig = go.Figure()
for plan, res in results:
    ts = res.timeseries
    fig.add_trace(go.Scatter(
        x=ts.index, y=ts["market_value"], mode="lines",
        name=plan["name"], line=dict(color=plan["color"], width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>市值 " + currency + "%{y:,.0f}<extra></extra>",
    ))

show_principal = st.checkbox("同時顯示各計畫累積投入本金（虛線）", value=False)
if show_principal:
    for plan, res in results:
        ts = res.timeseries
        fig.add_trace(go.Scatter(
            x=ts.index, y=ts["invested_cum"], mode="lines",
            name=f"{plan['name']}·本金",
            line=dict(color=plan["color"], width=1, dash="dot"),
            opacity=0.6, hoverinfo="skip",
        ))

base_layout(fig)
# use_container_width + responsive=True 是手機自適應寬度的關鍵
st.plotly_chart(fig, use_container_width=True, config={"responsive": True,
                                                       "displayModeBar": False})


# ------------------------------------------------------------------
#  區塊 C：細節下探（單一計畫「本金 vs 市值」）
# ------------------------------------------------------------------
st.subheader("細節下探：本金 vs 市值")

# 用索引當選項、代碼當顯示文字，避免兩個計畫同代碼時互相覆蓋
pick = st.selectbox(
    "選擇要下探的計畫",
    options=list(range(len(results))),
    format_func=lambda i: f"{results[i][0]['name']}（{i+1}）",
)
plan, res = results[pick]
ts = res.timeseries

fig2 = go.Figure()
fig2.add_trace(go.Scatter(
    x=ts.index, y=ts["invested_cum"], name="累積本金",
    mode="lines", line=dict(color="#94a3b8", width=2, dash="dash"),
    fill="tozeroy", fillcolor="rgba(148,163,184,0.15)",
    hovertemplate="%{x|%Y-%m-%d}<br>本金 " + currency + "%{y:,.0f}<extra></extra>",
))
fig2.add_trace(go.Scatter(
    x=ts.index, y=ts["market_value"], name="市值",
    mode="lines", line=dict(color=plan["color"], width=2.5),
    hovertemplate="%{x|%Y-%m-%d}<br>市值 " + currency + "%{y:,.0f}<extra></extra>",
))
base_layout(fig2)
st.plotly_chart(fig2, use_container_width=True, config={"responsive": True,
                                                        "displayModeBar": False})

st.caption("※ 年化報酬率採 XIRR（依實際現金流日期折現），較適用於扣款日不規則的定期定額。")
