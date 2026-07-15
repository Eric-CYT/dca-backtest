# 📈 全球定期定額 (DCA) 回測工具

支援**多情境對比**與**階梯式動態扣款 (Step-up DCA)** 的定期定額回測工具。
資料來自 `yfinance`，涵蓋全球市場（美股 `AAPL`、`VOO`；台股 `2330.TW`；倫敦 `VWRA.L`；港股 `0700.HK` …）。
電腦版與手機版皆已做響應式優化。

---

## 🗂 檔案結構

四個程式檔全部放在 repo **根目錄**（扁平擺放）：

```
dca-backtest/
├── app.py            ← Streamlit 主程式（UI）
├── dca_engine.py     ← 回測核心（動態金額、交易日順延、XIRR）
├── data_fetcher.py   ← yfinance 資料抓取
├── requirements.txt  ← 套件清單
└── README.md
```

---

## 🚀 部署到 Streamlit Community Cloud（免費，從 GitHub 一鍵上線）

1. 在 GitHub 建一個新 repo（例如 `dca-backtest`），把上面四個程式檔上傳並 Commit。
2. 前往 **https://share.streamlit.io**，右上角用 **GitHub 登入**並授權。
3. 點 **「Create app」→「Deploy a public app from GitHub」**。
4. 填三個欄位：
   - **Repository**：`你的帳號/dca-backtest`
   - **Branch**：`main`
   - **Main file path**：`app.py`
5. 點 **「Deploy」**，等 2–3 分鐘（它會自動讀 `requirements.txt` 安裝套件）。
6. 完成後會得到固定網址，例如 `https://xxx.streamlit.app`，手機／電腦都能開。
   之後只要更新 GitHub 上的檔案，它會**自動重新部署**。

> ⚠️ 小提醒：雲端環境偶爾會被 Yahoo 限流，若某次抓不到資料，重跑一次通常就好。

---

## 💻 在本機執行（可選）

```bash
pip install -r requirements.txt
streamlit run app.py
```

瀏覽器開 `http://localhost:8501`；停止程式在終端機按 `Ctrl + C`。

---

## ✨ 功能

- **多組計畫對比**：每組可設不同標的與不同階梯金額，用顏色標籤區分。
- **階梯式動態扣款**：例如 `3000, 5000, 8000` 代表第 1／2／3 年金額；超過年數沿用最後一格。
- **交易日順延**：遇假日自動買在下一個有效交易日。
- **核心績效**：總投入、累積股數、期末市值、總報酬率，及以 **XIRR** 計算的年化報酬率。
- **響應式圖表**：Plotly `autosize`、圖例置頂橫排（手機不擋線）、表格可橫向捲動。

---

## 🧮 年化報酬率說明

採 **XIRR**（依實際現金流日期折現）而非固定期距的 IRR，因為定期定額的扣款日會因
月份長短與交易日順延而不規則，XIRR 才是全球市場通用且較精確的年化算法。
