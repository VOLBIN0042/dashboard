"""執行：streamlit run sales_dashboard.py"""
from hmac import compare_digest
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# 同一個 Streamlit 工作階段登入後，互動造成的重新執行會略過驗證。
if not st.session_state.get("authenticated", False):
    # 用表單收集密碼，提交後清空輸入框。
    with st.form("login", clear_on_submit=True):
        entered_password = st.text_input("請輸入密碼", type="password")
        submitted = st.form_submit_button("登入")

    if submitted:
        # 從 Secrets 讀取密碼。設定缺漏時停止，避免開放儀表板。
        try:
            admin_password = st.secrets["passwords"]["admin"]
        except (FileNotFoundError, KeyError, TypeError):
            st.error("登入設定不完整，請聯絡管理員。")
            st.stop()

        if not isinstance(admin_password, str) or not admin_password:
            st.error("登入設定不完整，請聯絡管理員。")
            st.stop()

        # 比對 UTF-8 位元組以支援中文密碼，只記住登入狀態。
        if compare_digest(entered_password.encode("utf-8"), admin_password.encode("utf-8")):
            st.session_state["authenticated"] = True
            st.rerun()

        st.error("密碼錯誤，請再試一次。")

    # 未登入時在這裡停止，不讀取營收資料或顯示儀表板。
    st.stop()

st.set_page_config(page_title="老闆儀表板", page_icon="📊", layout="wide")
st.title("📊 老闆儀表板")

DEFAULT_CSV = Path(__file__).with_name("sales_2026.csv")
has_default_csv = DEFAULT_CSV.is_file()
st.sidebar.header("篩選條件")
upload_label = "上傳營收 CSV（選填）" if has_default_csv else "上傳營收 CSV"
uploaded = st.sidebar.file_uploader(upload_label, type=["csv"])


def read_sales(source):
    data = pd.read_csv(source)
    required = ["date", "product", "salesperson", "revenue", "cost", "customer"]
    missing = set(required) - set(data.columns)
    if missing:
        raise ValueError("缺少欄位：" + "、".join(sorted(missing)))
    if data.empty or data[required].isna().any().any():
        raise ValueError("資料為空，或必要欄位有空值。")
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    for column in ["revenue", "cost"]:
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not data[column].map(lambda x: float("-inf") < x < float("inf")).all():
            raise ValueError(f"{column} 含無效數值。")
    if (data["revenue"] < 0).any():
        raise ValueError("營收含負數，請先確認退貨或折讓的處理方式。")
    data["profit"] = data["revenue"] - data["cost"]
    return data.sort_values("date")


if uploaded is None and not has_default_csv:
    st.info("請從側邊欄上傳營收 CSV，即可查看儀表板。")
    st.stop()

try:
    df = read_sales(uploaded if uploaded is not None else DEFAULT_CSV)
except Exception as error:
    st.error(f"無法載入資料：{error}")
    st.info("請將 sales_2026.csv 放在程式旁，或從側邊欄上傳。")
    st.stop()

first_date, last_date = df["date"].min().date(), df["date"].max().date()
dates = st.sidebar.date_input("日期範圍", value=(first_date, last_date),
                              min_value=first_date, max_value=last_date, format="YYYY/MM/DD")
products = sorted(df["product"].unique().tolist())
selected_products = st.sidebar.multiselect("產品", products, default=products)
target = st.sidebar.number_input("公司每月目標營收（示範值，請調整）", min_value=0.0,
                                  value=900000.0, step=10000.0, format="%.0f")
st.sidebar.caption("目標線為公司整體月目標，不隨產品選取比例分攤。")
if not isinstance(dates, (tuple, list)) or len(dates) != 2:
    st.info("請選擇開始與結束日期。")
    st.stop()
start, end = map(pd.Timestamp, dates)
filtered = df[df["date"].between(start, end) & df["product"].isin(selected_products)].copy()
st.caption(f"篩選：{start:%Y/%m/%d}–{end:%Y/%m/%d}｜{len(selected_products)} 種產品｜{len(filtered):,} 筆交易。金額沿用原檔單位，未指定幣別。")

# KPI 採篩選結束日所在月份，且只計入所選日期；比較期為同一日期區間往前移一個月。
month_start = end.to_period("M").start_time
kpi_start = max(start, month_start)
previous_start = kpi_start - pd.DateOffset(months=1)
previous_end = end - pd.DateOffset(months=1)
current = filtered[filtered["date"].between(kpi_start, end)]
previous = df[df["date"].between(previous_start, previous_end) & df["product"].isin(selected_products)]
source_current = df[df["date"].between(kpi_start, end)]
source_previous = df[df["date"].between(previous_start, previous_end)]
revenue, profit = current["revenue"].sum(), current["profit"].sum()
previous_revenue = previous["revenue"].sum()
available = not source_current.empty and bool(selected_products)
delta = (f"{(revenue / previous_revenue - 1):+.1%} vs 上月同期"
         if available and not source_previous.empty and previous_revenue != 0 else None)
first_purchase = df.groupby("customer")["date"].min()
new_customers = sum(kpi_start <= first_purchase[c] <= end for c in current["customer"].unique())
st.subheader(f"{end.year} 年 {end.month} 月關鍵 KPI")
st.caption(f"本期 {kpi_start:%m/%d}–{end:%m/%d}；比較期 {previous_start:%Y/%m/%d}–{previous_end:%m/%d}（同產品條件）。")
cards = st.columns(4)
cards[0].metric("本月營收", f"{revenue:,.0f}" if available else "無資料", delta=delta)
cards[1].metric("本月利潤率", f"{profit/revenue:.1%}" if available and revenue else "不適用")
cards[2].metric("新客戶數", f"{new_customers:,}" if available else "無資料")
cards[3].metric("毛利", f"{profit:,.0f}" if available else "無資料")
if delta is None:
    st.caption("營收變化率未顯示：本期或比較期缺資料、未選產品，或比較期營收為零。")

if filtered.empty:
    st.info("目前條件沒有交易，請調整日期或產品。")
else:
    def style(figure):
        figure.update_layout(font=dict(family="Microsoft JhengHei, sans-serif"),
                             margin=dict(l=25, r=25, t=55, b=35), height=400)
        return figure

    left, right = st.columns(2)
    months = pd.period_range(start.to_period("M"), end.to_period("M"), freq="M")
    monthly = filtered.groupby(filtered["date"].dt.to_period("M"))["revenue"].sum()
    coverage = set(df[df["date"].between(start, end)]["date"].dt.to_period("M"))
    values = [float(monthly.get(m, 0)) if m in coverage else None for m in months]
    trend = go.Figure()
    trend.add_scatter(x=months.astype(str).tolist(), y=values, name="營收", mode="lines+markers",
                      hovertemplate="%{x}<br>營收 %{y:,.0f}<extra></extra>")
    trend.add_scatter(x=months.astype(str).tolist(), y=[target]*len(months), name="公司月目標",
                      mode="lines", line=dict(dash="dash", color="#ef4444"))
    trend.update_layout(title="月營收趨勢與目標", xaxis_title="月份", yaxis_title="營收")
    left.plotly_chart(style(trend), width="stretch")
    left.caption("起訖月份可能僅涵蓋部分日期；目標仍為完整月份的公司目標。無來源資料月份留空。")

    totals = filtered.groupby("product")["revenue"].sum().sort_values(ascending=False)
    pie_data = totals.iloc[:5].rename_axis("產品").reset_index(name="營收")
    if len(totals) > 5:
        pie_data.loc[len(pie_data)] = ["其他", totals.iloc[5:].sum()]
    if totals.sum() > 0:
        pie = px.pie(pie_data, names="產品", values="營收", hole=.45, title="產品營收占比｜前五大＋其他")
        right.plotly_chart(style(pie), width="stretch")
    else:
        right.info("所選交易營收皆為零，無法計算產品占比。")

    scatter = px.scatter(filtered, x="cost", y="profit", size="revenue", color="product",
        hover_name="product", hover_data={"customer":True,"salesperson":True,"date":True,"revenue":":,.0f","cost":":,.0f","profit":":,.0f"},
        labels={"cost":"成本","profit":"毛利","product":"產品類別","revenue":"營收","customer":"客戶","salesperson":"業務員","date":"日期"},
        size_max=45, title="成本 vs 毛利｜每點一筆交易，大小代表營收")
    st.plotly_chart(style(scatter), width="stretch")

with st.expander("資料與計算口徑"):
    st.write("毛利＝營收－成本；利潤率＝毛利÷營收，未扣除其他營業費用。資料沒有額外類別欄位，因此散布圖以產品著色。")
    st.write("新客戶依完整輸入檔中首次交易日期判定，並須在本期及所選產品中有交易。缺少更早歷史，無法確認是否為公司真正首購。")
    st.write("本月指所選結束日期的月份。KPI 只納入該月與篩選日期的交集；上月同期將本期起訖日期各往前移一個月，月底日期自動截至該月最後一天。")
    st.write("來源未提供正式預算，900,000 僅為可調整的示範公司月目標。")
