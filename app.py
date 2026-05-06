"""
基金智管家 - 支付宝场外基金智能助手
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.fund_data import (
    get_fund_estimate, get_fund_name, get_fund_nav_history,
    calculate_holding_days, format_change_pct,
    is_trading_day, is_trading_time, get_30_min_warning,
)
from utils.ai_advice import (
    generate_ai_advice, get_api_key as get_deepseek_key,
    has_api_key as has_deepseek_key,
)

# ============== 页面配置 ==============
st.set_page_config(
    page_title="基金智管家",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============== 数据路径 ==============
DATA_DIR = Path(__file__).parent / "data"
HOLDINGS_FILE = DATA_DIR / "holdings.json"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"

# ============== 缓存层 ==============
# 避免同一次 Session 内对同一基金代码重复请求 API


def _get_estimate_cached(fund_code, cache_ttl=120):
    """带 Session 缓存的估值获取"""
    cache = st.session_state.setdefault("estimate_cache", {})
    now = time.time()
    if fund_code in cache and (now - cache[fund_code]["time"]) < cache_ttl:
        return cache[fund_code]["data"]
    result = get_fund_estimate(fund_code)
    cache[fund_code] = {"data": result, "time": now}
    return result


def _clear_estimate_cache():
    """清空估值缓存（用于强制刷新）"""
    st.session_state["estimate_cache"] = {}


# ============== 数据层 ==============
# 策略：st.session_state 作为主存储（页面切换不丢），JSON 文件作为持久化备份
# 所有写操作同时写入两者，读操作优先从 session_state 返回

def _init_data_files():
    """确保数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json_to_df(filepath):
    """从 JSON 文件加载 DataFrame"""
    try:
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8").strip()
            if content:
                return pd.DataFrame(json.loads(content))
    except Exception:
        pass
    return pd.DataFrame()


def _save_df_to_json(filepath, df):
    """将 DataFrame 保存到 JSON 文件"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        filepath.write_text(
            json.dumps(df.to_dict("records"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass  # 文件写入失败不阻断业务


def _has_data():
    """检查是否有持仓或关注数据"""
    if "_data_checked" in st.session_state:
        return st.session_state["_data_checked"]
    has = (
        not load_holdings().empty
        or not load_watchlist().empty
    )
    st.session_state["_data_checked"] = has
    return has


# ---------- 持仓 ----------

def load_holdings():
    if "_holdings_df" in st.session_state:
        return st.session_state["_holdings_df"].copy()
    df = _load_json_to_df(HOLDINGS_FILE)
    st.session_state["_holdings_df"] = df.copy()
    return df


def save_holdings(df):
    st.session_state["_holdings_df"] = df.copy()
    st.session_state["_data_checked"] = not df.empty
    _save_df_to_json(HOLDINGS_FILE, df)


def add_holding(fund_code, fund_name, buy_amount, buy_date,
                nav_at_buy=None, target_return=10.0, fund_type="C"):
    """添加持仓记录"""
    df = load_holdings()
    shares = None
    if nav_at_buy and nav_at_buy > 0:
        shares = buy_amount / nav_at_buy

    new_id = df["id"].max() + 1 if not df.empty else 1
    record = {
        "id": int(new_id),
        "fund_code": fund_code,
        "fund_name": fund_name,
        "buy_amount": buy_amount,
        "buy_date": buy_date,
        "nav_at_buy": nav_at_buy,
        "shares": shares,
        "target_return": target_return,
        "fund_type": fund_type,
        "created_at": datetime.now().isoformat(),
    }
    df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
    save_holdings(df)


def delete_holding(holding_id):
    df = load_holdings()
    df = df[df["id"] != holding_id].copy()
    save_holdings(df)


# ---------- 关注列表 ----------

def load_watchlist():
    if "_watchlist_df" in st.session_state:
        return st.session_state["_watchlist_df"].copy()
    df = _load_json_to_df(WATCHLIST_FILE)
    st.session_state["_watchlist_df"] = df.copy()
    return df


def save_watchlist(df):
    st.session_state["_watchlist_df"] = df.copy()
    st.session_state["_data_checked"] = not df.empty
    _save_df_to_json(WATCHLIST_FILE, df)


def add_to_watchlist(fund_code, fund_name):
    df = load_watchlist()
    if not df.empty and fund_code in df["fund_code"].values:
        return  # 已存在
    record = {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "added_at": datetime.now().isoformat(),
    }
    df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
    save_watchlist(df)


def remove_from_watchlist(fund_code):
    df = load_watchlist()
    df = df[df["fund_code"] != fund_code].copy()
    save_watchlist(df)


# ---------- 导入 / 导出 ----------

def export_data():
    holdings = load_holdings()
    watchlist = load_watchlist()
    payload = {
        "export_time": datetime.now().isoformat(),
        "version": "1.0",
        "holdings": holdings.to_dict("records") if not holdings.empty else [],
        "watchlist": watchlist.to_dict("records") if not watchlist.empty else [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def import_data(json_str):
    try:
        data = json.loads(json_str)
        if "holdings" in data:
            df = pd.DataFrame(data["holdings"])
            # 确保 id 字段为整数
            if "id" in df.columns:
                df["id"] = df["id"].astype(int)
            save_holdings(df)
        if "watchlist" in data:
            save_watchlist(pd.DataFrame(data["watchlist"]))
        return True, "数据导入成功！"
    except Exception as e:
        return False, f"导入失败：{str(e)}"


# ============== CSS 样式 ==============

CSS = """
<style>
    /* 红涨绿跌（中国惯例） */
    .fund-up { color: #FF4136; font-weight: bold; }
    .fund-down { color: #2ECC40; font-weight: bold; }

    /* 卡片 */
    .metric-card {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        margin: 5px 0;
    }
    .warning-card {
        background-color: #fff3cd;
        padding: 15px;
        border-radius: 5px;
        border-left: 4px solid #ffc107;
        margin: 10px 0;
    }
    .danger-card {
        background-color: #f8d7da;
        padding: 15px;
        border-radius: 5px;
        border-left: 4px solid #dc3545;
        margin: 10px 0;
    }
    .success-card {
        background-color: #d4edda;
        padding: 15px;
        border-radius: 5px;
        border-left: 4px solid #28a745;
        margin: 10px 0;
    }
    .main-title {
        font-size: 28px;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        padding: 20px 0;
    }
    .risk-warning {
        background-color: #fff3cd;
        padding: 15px;
        border-radius: 5px;
        border-left: 4px solid #ffc107;
        margin-top: 30px;
    }
    .fixed-bottom-warning {
        position: fixed;
        bottom: 0; left: 0; right: 0;
        background-color: #fff3cd;
        padding: 10px 20px;
        border-top: 2px solid #ffc107;
        text-align: center;
        z-index: 999;
    }
    /* 导入提示高亮 */
    .import-banner {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 40px;
        border-radius: 15px;
        text-align: center;
        margin: 30px 0;
    }
    .import-banner h2 { color: white; margin-bottom: 15px; }
    .import-banner p { color: rgba(255,255,255,0.9); font-size: 16px; }
</style>
"""

# ============== 全局组件 ==============


def _render_30_warning():
    """14:30 操作提醒（全局显示）"""
    if get_30_min_warning() and is_trading_day():
        st.markdown("""
        <div class="warning-card">
            <h3>⏰ 14:30 操作提醒</h3>
            <p>距离 15:00 收盘还有 <strong>30 分钟</strong>！
            场外基金在 15:00 前的操作按 <strong>今天净值</strong> 确认，
            15:00 后按 <strong>下一交易日净值</strong> 确认。</p>
            <p>请确认今日是否需要买卖操作~</p>
        </div>
        """, unsafe_allow_html=True)


def _render_sidebar_status():
    """侧边栏顶部状态"""
    if is_trading_day():
        if is_trading_time():
            st.success("🟢 交易时间（9:30-15:00）")
        else:
            st.info("🟡 非交易时间")
    else:
        st.warning("🟠 今日非交易日")


def _render_sidebar_quick_add():
    """侧边栏快捷添加关注"""
    st.subheader("➕ 快捷添加")
    with st.expander("添加关注", expanded=False):
        with st.form("add_watch_form", clear_on_submit=True):
            code = st.text_input("基金代码", placeholder="000001", label_visibility="collapsed")
            if st.form_submit_button("添加"):
                if code:
                    name = get_fund_name(code)
                    add_to_watchlist(code, name)
                    _clear_estimate_cache()
                    st.success("已添加关注！")
                    st.rerun()


def _render_sidebar_ai_config():
    """侧边栏 DeepSeek API Key 配置"""
    st.subheader("🤖 AI 建议")

    has_key = has_deepseek_key()
    if has_key:
        st.success("✅ AI 已就绪", help="DeepSeek API Key 已配置")
        if st.button("🔄 刷新 AI 缓存", key="clear_ai_cache", use_container_width=True):
            st.session_state.pop("ai_advice_cache", None)
            st.rerun()
    else:
        st.warning("未配置 AI Key", help="配置后可在「操作建议」页面使用 AI 深度分析")
        with st.expander("配置 DeepSeek Key", expanded=False):
            api_key = st.text_input(
                "输入 API Key",
                type="password",
                placeholder="sk-...",
                label_visibility="collapsed",
                key="ai_key_input",
            )
            if st.button("保存", use_container_width=True):
                if api_key.startswith("sk-"):
                    st.session_state["deepseek_api_key"] = api_key
                    st.success("已保存！")
                    st.rerun()
                else:
                    st.error("Key 格式不正确，应以 sk- 开头")
            st.caption(
                "Key 仅保存在当前浏览器 session 中，关闭页面后需重新输入。"
                "也可在 .streamlit/secrets.toml 中配置。"
            )


def _render_sidebar_reminder():
    """侧边栏时间提醒"""
    st.markdown("""
    <div class="metric-card">
        <h4>⏰ 重要时间提醒</h4>
        <ul>
            <li><strong>11:00</strong> - 盘中估值播报</li>
            <li><strong>14:30</strong> - 操作提醒 ⚠️</li>
            <li><strong>15:00</strong> - 当日交易截止</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)


def _render_disclaimer():
    """风险提示"""
    st.markdown("""
    <div class="risk-warning">
        <h4>⚠️ 风险提示</h4>
        <p>基金投资有风险，请根据自身风险承受能力谨慎决策。</p>
        <p><strong>本系统所有分析仅供参考，不构成投资建议。</strong></p>
    </div>
    """, unsafe_allow_html=True)


# ============== 导入引导页 ==============


def _render_import_guide():
    """
    首次使用 / 数据丢失时的导入引导
    返回 True 表示数据已就绪，False 表示仍为空
    """
    st.markdown('<h1 class="main-title">💰 基金智管家</h1>', unsafe_allow_html=True)

    st.markdown("""
    <div class="import-banner">
        <h2>👋 欢迎使用基金智管家！</h2>
        <p>检测到您还没有持仓数据，请通过以下方式开始：</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📥 恢复备份")
        with st.container(border=True):
            uploaded = st.file_uploader("选择之前导出的 JSON 文件", type=["json"])
            if uploaded and st.button("✅ 确认导入", type="primary", use_container_width=True):
                ok, msg = import_data(uploaded.getvalue().decode("utf-8"))
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with col2:
        st.markdown("### 🆕 全新开始")
        with st.container(border=True):
            st.write("还没有数据？直接进入主界面，从侧边栏开始添加基金吧！")
            if st.button("🚀 开始使用", use_container_width=True):
                st.session_state["_data_checked"] = True
                st.rerun()

    st.info(
        "💡 **Streamlit Cloud 免费版提醒**：应用重启后数据可能丢失，"
        "建议定期使用「一键导出」功能备份数据。"
    )
    return False


# ============== 估值看板 ==============


def render_estimate_board():
    """基金实时估值看板"""
    st.header("📊 基金实时估值")

    watchlist = load_watchlist()
    holdings = load_holdings()

    all_codes = set()
    if not watchlist.empty:
        all_codes.update(watchlist["fund_code"].tolist())
    if not holdings.empty:
        all_codes.update(holdings["fund_code"].tolist())

    if not all_codes:
        st.info("💡 暂无关注的基金，请在侧边栏添加基金代码")
        return

    # 强制刷新按钮
    col_left, col_right = st.columns([6, 1])
    with col_right:
        if st.button("🔄 刷新估值", use_container_width=True):
            _clear_estimate_cache()

    # 批量获取估值
    estimates = []
    sorted_codes = sorted(all_codes)

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, code in enumerate(sorted_codes):
        status_text.text(f"正在获取 {code} 的估值…")
        est = _get_estimate_cached(code)
        if est["success"]:
            est["in_watchlist"] = not watchlist.empty and code in watchlist["fund_code"].values
            est["in_holdings"] = not holdings.empty and code in holdings["fund_code"].values
            estimates.append(est)

        progress_bar.progress((i + 1) / len(sorted_codes))
        if i < len(sorted_codes) - 1:
            time.sleep(0.3)

    progress_bar.empty()
    status_text.empty()

    if not estimates:
        st.warning("暂时无法获取估值数据，请稍后再试（服务器在国外，访问国内 API 可能较慢）")
        return

    # 按涨跌幅排序
    estimates.sort(key=lambda x: x["estimate_change"], reverse=True)

    st.subheader(f"📋 估值概览（共 {len(estimates)} 只基金）")

    avg_change = sum(e["estimate_change"] for e in estimates) / len(estimates)
    up_count = sum(1 for e in estimates if e["estimate_change"] > 0)
    down_count = sum(1 for e in estimates if e["estimate_change"] < 0)

    c1, c2, c3 = st.columns(3)
    c1.metric("📈 上涨", up_count)
    c2.metric("📉 下跌", down_count)
    c3.metric("平均涨跌", f"{avg_change:+.2f}%", "乐观" if avg_change > 0 else "谨慎")

    # 表格
    tbl = pd.DataFrame({
        "基金代码": [e["code"] for e in estimates],
        "基金名称": [e["name"] for e in estimates],
        "估算净值": [f"{e['estimate']:.4f}" for e in estimates],
        "估算涨跌%": [e["estimate_change"] for e in estimates],
        "关注": ["⭐" if e.get("in_watchlist") else "" for e in estimates],
        "持仓": ["💼" if e.get("in_holdings") else "" for e in estimates],
    })

    def _color(val):
        if val > 0:
            return "color: #FF4136"
        if val < 0:
            return "color: #2ECC40"
        return ""

    st.dataframe(
        tbl.style.applymap(_color, subset=["估算涨跌%"]),
        use_container_width=True,
        height=400,
    )

    st.caption(f"🕐 数据时间：{estimates[0]['date']} ｜ 估值仅供参考，实际净值以晚上公布的为准")

    with st.expander("💡 关于盘中估值"):
        st.markdown("""
        - 盘中估值是根据基金持仓股票的实时价格估算的净值
        - **估算净值 ≠ 实际净值**，可能有偏差
        - 实际净值以基金公司晚上公布的为准
        - 估值更新时间：交易日 9:30-15:00
        """)


# ============== 持仓管理 ==============


def render_portfolio():
    """持仓管理页面"""
    st.header("💼 我的持仓")

    # ----- 导入导出 -----
    export_btn, import_area = st.columns(2)
    with export_btn:
        st.download_button(
            label="📤 一键导出持仓（备份）",
            data=export_data(),
            file_name=f"fund_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
        )
    with import_area:
        uploaded = st.file_uploader("📥 恢复备份", type=["json"], label_visibility="collapsed")
        if uploaded:
            if st.button("确认导入", use_container_width=True):
                ok, msg = import_data(uploaded.getvalue().decode("utf-8"))
                if ok:
                    st.success(msg)
                    _clear_estimate_cache()
                    st.rerun()
                else:
                    st.error(msg)

    st.markdown("---")

    tab_list, tab_add = st.tabs(["📋 持仓列表", "➕ 添加持仓"])

    # ===== 添加持仓 =====
    with tab_add:
        st.subheader("添加新持仓")
        with st.form("add_holding_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                fund_code = st.text_input("基金代码", placeholder="如 000001").strip()
            with col2:
                if fund_code:
                    fname = get_fund_name(fund_code)
                    if fname != fund_code:
                        st.text_input("基金名称", value=fname, disabled=True)
                    else:
                        fname = st.text_input("基金名称", placeholder="请输入基金名称")
                else:
                    fname = st.text_input("基金名称", placeholder="请先输入基金代码")

            col3, col4 = st.columns(2)
            with col3:
                buy_amount = st.number_input("买入金额（元）", min_value=1.0, step=100.0, value=1000.0)
            with col4:
                buy_date = st.date_input("买入日期", value=datetime.now())

            col5, col6 = st.columns(2)
            with col5:
                nav = None
                if fund_code:
                    with st.spinner("获取净值中…"):
                        est = _get_estimate_cached(fund_code, cache_ttl=0)  # 强制刷新
                        if est["success"]:
                            nav = est["estimate"]
                            st.text_input("参考净值（估算）", value=f"{nav:.4f}", disabled=True)
                if not nav:  # 没获取到就手动输入
                    nav = st.number_input("买入净值（未知填 1）", min_value=0.0001,
                                          step=0.0001, value=1.0, format="%.4f")
            with col6:
                fund_type_label = st.selectbox(
                    "基金类型",
                    ["C类（无申购费）", "A类（有申购费）"],
                    help="短期持有选 C 类，长期持有选 A 类",
                )
                fund_type = "C" if "C类" in fund_type_label else "A"

            target_return = st.slider("止盈目标收益率（%）", 5, 50, 10,
                                      help="达到目标收益率后提醒卖出")

            submitted = st.form_submit_button("✅ 添加持仓", type="primary", use_container_width=True)
            if submitted:
                if fund_code and buy_amount > 0:
                    final_name = fname if fname else fund_code
                    add_holding(
                        fund_code=fund_code,
                        fund_name=final_name,
                        buy_amount=buy_amount,
                        buy_date=buy_date.strftime("%Y-%m-%d"),
                        nav_at_buy=nav,
                        target_return=float(target_return),
                        fund_type=fund_type,
                    )
                    _clear_estimate_cache()
                    st.success(f"✅ 已添加 {final_name} 的持仓！")
                    st.rerun()
                else:
                    st.warning("请填写基金代码和买入金额")

    # ===== 持仓列表 =====
    with tab_list:
        holdings = load_holdings()
        if holdings.empty:
            st.info("💡 暂无持仓，点击上方「添加持仓」开始记录")
            return

        # 计算结果
        results, total_value, total_cost, total_profit = _calc_portfolio(holdings)

        total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💰 总资产", f"¥{total_value:,.2f}")
        c2.metric("💵 总投入", f"¥{total_cost:,.2f}")
        c3.metric("📈 总收益", f"¥{total_profit:,.2f}", f"{total_profit_pct:+.2f}%")
        c4.metric("📊 持仓数", len(holdings))

        st.markdown("---")
        st.subheader("📋 持仓详情")

        for r in results:
            with st.container():
                if r["warning_7days"]:
                    st.markdown(f"""
                    <div class="danger-card">
                        <h4>⚠️ {r["fund_name"]}（{r["fund_code"]}）</h4>
                        <p><strong>持有不足 7 天！</strong> 提前赎回将收取 <strong>1.5%</strong> 惩罚性赎回费</p>
                    </div>
                    """, unsafe_allow_html=True)
                elif r["reached_target"]:
                    st.markdown(f"""
                    <div class="success-card">
                        <h4>🎉 {r["fund_name"]}（{r["fund_code"]}）</h4>
                        <p>收益率 <strong>{r["profit_pct"]:.2f}%</strong>，已达止盈目标 {r["target_return"]}%</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"### {r['fund_name']}（{r['fund_code']}）")

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.markdown("**买入信息**")
                    st.write(f"• 买入金额：¥{r['buy_amount']:,.2f}")
                    st.write(f"• 买入净值：{r['nav_at_buy']:.4f}")
                    st.write(f"• 买入日期：{r['buy_date']}")
                    st.write(f"• 持有份额：{r['shares']:.2f}")
                with col2:
                    st.markdown("**当前状态**")
                    if r["current_nav"]:
                        st.markdown(
                            f"• 当前净值：{r['current_nav']:.4f} "
                            + format_change_pct(r["estimate_change"]),
                            unsafe_allow_html=True,
                        )
                    else:
                        st.write("• 当前净值：获取中…")
                    st.write(f"• 持有天数：{r['hold_days']}天")
                    st.write(f"• 基金类型：{r['fund_type']}类")
                with col3:
                    st.markdown("**收益情况**")
                    color = "fund-up" if r["profit"] >= 0 else "fund-down"
                    st.markdown(
                        f"• 当前市值：<span class='{color}'>¥{r['current_value']:,.2f}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"• 收益金额：<span class='{color}'>¥{r['profit']:+,.2f}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"• 收益率：<span class='{color}'>{r['profit_pct']:+.2f}%</span>",
                        unsafe_allow_html=True,
                    )
                with col4:
                    st.markdown("**目标提醒**")
                    st.write(f"• 止盈目标：{r['target_return']}%")
                    if r["reached_target"]:
                        st.success("✅ 已达标！")
                    else:
                        remaining = r["target_return"] - r["profit_pct"]
                        st.info(f"还差 {remaining:.2f}%")

                if st.button(f"🗑️ 删除持仓", key=f"del_{r['id']}"):
                    delete_holding(r["id"])
                    st.rerun()
                st.markdown("---")

        # 持仓占比饼图
        valid = [r for r in results if r["current_value"] > 0]
        if valid:
            colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD", "#F7DC6F", "#BB8FCE"]
            fig = go.Figure(data=[go.Pie(
                labels=[r["fund_name"] for r in valid],
                values=[r["current_value"] for r in valid],
                hole=0.4,
                textinfo="percent+label",
                marker=dict(colors=colors),
            )])
            fig.update_layout(title="持仓占比", height=350)
            st.plotly_chart(fig, use_container_width=True)


def _calc_portfolio(holdings):
    """计算持仓盈亏明细"""
    results = []
    total_value = total_cost = total_profit = 0.0

    for _, row in holdings.iterrows():
        est = _get_estimate_cached(row["fund_code"])
        current_nav = est["estimate"] if est["success"] else None
        estimate_change = est["estimate_change"] if est["success"] else 0

        nav_at_buy = (
            row["nav_at_buy"]
            if pd.notna(row.get("nav_at_buy")) and row["nav_at_buy"]
            else 1.0
        )
        shares = row.get("shares")
        if pd.isna(shares) or not shares:
            shares = row["buy_amount"] / nav_at_buy if nav_at_buy > 0 else 0

        cost = float(row["buy_amount"])
        if current_nav and shares > 0:
            current_value = current_nav * float(shares)
            profit = current_value - cost
            profit_pct = (profit / cost * 100) if cost > 0 else 0
            total_value += current_value
            total_cost += cost
            total_profit += profit
        else:
            current_value = profit = profit_pct = 0.0

        hold_days = calculate_holding_days(row["buy_date"])

        results.append({
            "id": row["id"],
            "fund_code": row["fund_code"],
            "fund_name": row["fund_name"],
            "buy_amount": cost,
            "buy_date": row["buy_date"],
            "nav_at_buy": nav_at_buy,
            "shares": float(shares) if shares else 0,
            "current_nav": current_nav,
            "estimate_change": estimate_change,
            "current_value": current_value,
            "profit": profit,
            "profit_pct": profit_pct,
            "hold_days": hold_days,
            "warning_7days": hold_days < 7,
            "reached_target": profit_pct >= row.get("target_return", 10) if row.get("target_return") else False,
            "target_return": row.get("target_return", 10),
            "fund_type": row.get("fund_type", "C"),
        })

    return results, total_value, total_cost, total_profit


# ============== 净值走势 ==============


def render_nav_chart():
    """净值走势页面"""
    st.header("📈 净值走势")

    fund_code = st.text_input("基金代码", placeholder="如 000001", label_visibility="collapsed")
    if not fund_code:
        st.info("💡 请输入基金代码查看净值走势")
        return

    fund_name = get_fund_name(fund_code)
    if fund_name != fund_code:
        st.success(f"📌 {fund_name}")

    # 时间范围选择器放在请求前
    period = st.selectbox(
        "时间范围",
        ["近1月", "近3月", "近6月", "近1年"],
        index=3,
        horizontal=True,
    )

    days_map = {"近1月": 30, "近3月": 90, "近6月": 180, "近1年": 365}
    days = days_map[period]

    with st.spinner("获取净值数据中…"):
        nav_df = get_fund_nav_history(fund_code, days=365)  # 拉取全年用于均线

    if nav_df.empty:
        st.warning("暂时无法获取净值数据，请稍后再试")
        return

    start_date = datetime.now() - timedelta(days=days)
    plot_df = nav_df[nav_df["日期"] >= start_date].copy()

    if plot_df.empty:
        st.warning("该时间段内无数据")
        return

    # 均线
    plot_df["MA5"] = plot_df["单位净值"].rolling(5).mean()
    plot_df["MA20"] = plot_df["单位净值"].rolling(20).mean()
    plot_df["MA60"] = plot_df["单位净值"].rolling(60).mean()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=plot_df["日期"], y=plot_df["单位净值"],
        mode="lines", name="单位净值",
        line=dict(color="#1f77b4", width=2),
    ))
    if len(plot_df) >= 5:
        fig.add_trace(go.Scatter(
            x=plot_df["日期"], y=plot_df["MA5"],
            mode="lines", name="5日均线",
            line=dict(color="#FF6B6B", width=1, dash="dash"),
        ))
    if len(plot_df) >= 20:
        fig.add_trace(go.Scatter(
            x=plot_df["日期"], y=plot_df["MA20"],
            mode="lines", name="20日均线",
            line=dict(color="#4ECDC4", width=1, dash="dash"),
        ))
    if len(plot_df) >= 60:
        fig.add_trace(go.Scatter(
            x=plot_df["日期"], y=plot_df["MA60"],
            mode="lines", name="60日均线",
            line=dict(color="#FFEAA7", width=1, dash="dash"),
        ))

    fig.update_layout(
        title=f"{fund_name} 净值走势（{period}）",
        xaxis_title="日期",
        yaxis_title="单位净值",
        height=450,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

    if len(plot_df) > 1:
        latest = plot_df.iloc[-1]["单位净值"]
        first = plot_df.iloc[0]["单位净值"]
        ret = ((latest - first) / first) * 100
        c1, c2, c3 = st.columns(3)
        c1.metric("最新净值", f"{latest:.4f}", f"{ret:+.2f}%")
        c2.metric("期初净值", f"{first:.4f}")
        c3.metric(f"{period}收益", f"{ret:+.2f}%")


# ============== 操作建议 ==============


def render_advice():
    """智能操作建议页面"""
    st.header("💡 操作建议")

    holdings = load_holdings()
    if holdings.empty:
        st.info("💡 暂无持仓，请先添加持仓获取操作建议")
        return

    st.markdown("### 📋 持仓操作建议")

    for _, row in holdings.iterrows():
        est = _get_estimate_cached(row["fund_code"])
        if not est["success"]:
            st.warning(f"无法获取 {row['fund_name']} 的估值数据")
            continue

        current_nav = est["estimate"]
        estimate_change = est["estimate_change"]
        nav_at_buy = (
            row["nav_at_buy"]
            if pd.notna(row.get("nav_at_buy")) and row["nav_at_buy"]
            else 1.0
        )
        shares = row.get("shares")
        if pd.isna(shares) or not shares:
            shares = row["buy_amount"] / nav_at_buy
        current_value = current_nav * float(shares)
        cost = float(row["buy_amount"])
        profit = current_value - cost
        profit_pct = (profit / cost * 100) if cost > 0 else 0
        hold_days = calculate_holding_days(row["buy_date"])

        advice = generate_advice(
            fund_name=row["fund_name"],
            fund_code=row["fund_code"],
            estimate_change=estimate_change,
            profit_pct=profit_pct,
            hold_days=hold_days,
            target_return=row.get("target_return", 10.0),
            fund_type=row.get("fund_type", "C"),
        )

        with st.container():
            st.markdown(f"""
            <div class="{advice['style']}">
                <h4>{advice['icon']} {row['fund_name']}（{row['fund_code']}）</h4>
                <p><strong>当前估值涨跌：</strong>{estimate_change:+.2f}%</p>
                <p><strong>持仓收益：</strong>{profit_pct:+.2f}%（持有 {hold_days} 天）</p>
                <p><strong>建议：</strong>{advice['text']}</p>
                {advice['warning']}
            </div>
            """, unsafe_allow_html=True)
            st.markdown("---")

    # ========== AI 深度分析 ==========
    st.markdown("---")
    st.markdown("## 🤖 AI 深度分析")
    st.caption("基于 DeepSeek 大模型分析你的持仓数据，给出个性化操作建议")

    # 检查 AI 是否可用
    if has_deepseek_key():
        # 缓存 key: 用持仓 id 拼接的 hash 作为 key，数据变了就重新生成
        cache_key = "ai_advice_cache"
        holdings_hash = str(sorted(holdings["id"].tolist()) if "id" in holdings.columns else holdings.index.tolist())

        col1, col2 = st.columns([1, 5])
        with col1:
            if st.button("🚀 获取 AI 分析", type="primary", use_container_width=True):
                st.session_state[cache_key] = None  # 清旧缓存

        # 检查缓存是否有效
        cached = st.session_state.get(cache_key)
        if cached and cached.get("hash") == holdings_hash:
            advice_text = cached["text"]
            st.markdown("---")
            st.markdown(advice_text)
        elif st.session_state.get(cache_key) is None:
            # 没缓存或刚刚点了按钮 → 调 API
            # 构建估值缓存字典
            estimates_cache = {}
            for code in holdings["fund_code"].unique():
                est = _get_estimate_cached(code)
                estimates_cache[code] = est

            with st.spinner("🤔 AI 正在分析持仓数据…（约 10-30 秒）"):
                api_key = get_deepseek_key()
                advice_text, error = generate_ai_advice(
                    holdings_df=holdings,
                    estimates_cache=estimates_cache,
                    api_key=api_key,
                )

            if error:
                st.error(error)
                if "未配置" in error:
                    st.info("请在侧边栏配置 DeepSeek API Key")
            else:
                st.session_state[cache_key] = {
                    "hash": holdings_hash,
                    "text": advice_text,
                }
                st.markdown("---")
                st.markdown(advice_text)
                # 免责声明
                st.info(
                    "⚠️ AI 建议由大模型生成，仅供参考，不构成投资建议。"
                    "请结合自身情况独立决策。"
                )
        else:
            # 有缓存但 hash 变了 → 显示提示
            st.info("持仓数据已变化，点击「获取 AI 分析」重新生成")
    else:
        st.info("💡 在侧边栏配置 DeepSeek API Key 后即可使用 AI 深度分析")
        st.markdown("""
        <div class="metric-card">
            <h4>📌 为什么用 AI？</h4>
            <p>AI 分析会综合考虑你的持仓结构、每只基金的盈亏状况、
            持有时间和今日估值走势，给出比规则更灵活、更个性化的操作建议。</p>
            <p>需要 <strong>DeepSeek API Key</strong>，在左侧侧边栏配置即可。</p>
        </div>
        """, unsafe_allow_html=True)


def generate_advice(fund_name, fund_code, estimate_change, profit_pct,
                    hold_days, target_return, fund_type):
    """生成操作建议"""
    advice = {"icon": "📊", "text": "持有观望", "style": "metric-card", "warning": ""}

    if hold_days < 7:
        advice["warning"] = (
            '<p style="color:#dc3545;">'
            "<strong>⚠️ 持有不足 7 天，提前赎回将收取 1.5% 惩罚性赎回费！</strong>"
            "</p>"
        )

    if profit_pct >= target_return:
        advice["icon"] = "🎉"
        advice["text"] = f"收益率已达 {profit_pct:.2f}%，达到目标！建议分批止盈，锁定利润。"
        advice["style"] = "success-card"
        return advice

    if estimate_change <= -3:
        advice["icon"] = "📉"
        advice["text"] = (
            "今日跌幅较大，建议持有观察，7 天后再考虑操作。"
            if hold_days < 7
            else "今日跌幅较大，若认可长期价值可考虑逢低补仓。"
        )
        advice["style"] = "warning-card"
    elif estimate_change >= 3:
        advice["icon"] = "📈"
        if profit_pct > 0:
            advice["text"] = "今日涨幅较大，可考虑部分减仓，锁定部分利润。"
        else:
            advice["text"] = "今日表现强势，但持仓仍亏损，建议继续持有。"
        advice["style"] = "success-card" if profit_pct > 0 else "metric-card"
    else:
        if profit_pct > 0:
            advice["icon"] = "✅"
            advice["text"] = "表现稳健，继续持有，等待达到止盈目标。"
        elif profit_pct < -10:
            advice["icon"] = "🔍"
            advice["text"] = "短期亏损较大，请确认基金经理和投资方向是否认可。"
        else:
            advice["icon"] = "⏸️"
            advice["text"] = "波动正常，建议耐心持有，不频繁操作。"

    return advice


# ============== 基金搜索 ==============


def render_fund_search():
    """基金搜索页面"""
    st.header("🔍 基金搜索")

    search_code = st.text_input("基金代码", placeholder="如 000001", label_visibility="collapsed")
    if not search_code:
        st.info("💡 请输入基金代码查询信息")
        return

    fund_name = get_fund_name(search_code)
    if fund_name != search_code:
        st.success(f"📌 {fund_name}")

    est = _get_estimate_cached(search_code)
    if est["success"]:
        st.markdown("### 📊 盘中估值")
        c1, c2, c3 = st.columns(3)
        c1.metric("估算净值", f"{est['estimate']:.4f}")
        c2.metric("估算涨跌", f"{est['estimate_change']:+.2f}%")
        c3.metric("最新净值", f"{est['net_value']:.4f}")
        st.caption(f"数据时间：{est['date']}")

    # 关注按钮
    if st.button("⭐ 加入关注", key="add_watch_search"):
        add_to_watchlist(search_code, fund_name)
        _clear_estimate_cache()
        st.success("已加入关注列表！")


# ============== 主界面 ==============


def main():
    st.markdown(f"<h1 class='main-title'>💰 基金智管家</h1>", unsafe_allow_html=True)
    st.markdown(CSS, unsafe_allow_html=True)

    # 初始化数据
    _init_data_files()

    # ---- 首次使用 / 数据丢失 → 导入引导 ----
    if not _has_data():
        _render_import_guide()
        return  # 数据就绪之前不显示主界面

    # ---- 侧边栏 ----
    with st.sidebar:
        st.header("📌 功能导航")
        _render_sidebar_status()
        st.markdown("---")

        quick_action = st.radio(
            "选择功能",
            ["📊 估值看板", "💼 持仓管理", "📈 净值走势", "💡 操作建议", "🔍 基金搜索"],
            label_visibility="collapsed",
        )

        st.markdown("---")
        _render_sidebar_quick_add()
        st.markdown("---")
        _render_sidebar_ai_config()
        st.markdown("---")
        _render_sidebar_reminder()
        _render_disclaimer()

    # ---- 全局 14:30 提醒 ----
    _render_30_warning()

    # ---- 主内容 ----
    if quick_action == "📊 估值看板":
        render_estimate_board()
    elif quick_action == "💼 持仓管理":
        render_portfolio()
    elif quick_action == "📈 净值走势":
        render_nav_chart()
    elif quick_action == "💡 操作建议":
        render_advice()
    elif quick_action == "🔍 基金搜索":
        render_fund_search()

    # ---- 底部免责 ----
    st.markdown("""
    <div class="risk-warning" style="margin-top:50px;">
        <h4>⚠️ 免责声明</h4>
        <p>本应用提供的所有数据和分析仅供参考，不构成任何投资建议。</p>
        <p>基金投资有风险，入市需谨慎。过往业绩不代表未来表现。</p>
        <p>盘中估值为预估值，与实际净值可能存在偏差，最终以基金公司公布的净值为准。</p>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
