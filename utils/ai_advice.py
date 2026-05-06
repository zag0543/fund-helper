"""
AI 投资建议模块 - 基于 DeepSeek API

使用前需要在以下位置之一配置 API Key（优先级从高到低）：
1. `.streamlit/secrets.toml`：`DEEPSEEK_API_KEY = "sk-..."`
2. 应用侧边栏手动输入（仅当前 session 有效）
"""
from datetime import date, datetime

import pandas as pd
import streamlit as st
from openai import OpenAI

# ============== 配置 ==============
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# 如 deepseek 有新的模型 ID，改这里即可
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是一位专业的基金投资顾问，根据用户提供的持仓信息和市场情况，给出具体的操作建议。

## 输出格式要求

请用 Markdown 格式输出，包含以下三个部分：

### 1️⃣ 组合概况
简要评价整体持仓的收益状况、风险分布和合理性。

### 2️⃣ 逐只基金分析
每只基金独立一段，包含：
- 当前盈亏评价（持有时间是否足够、收益是否合理）
- 今日涨跌含义（结合盘面估值的解读）
- 具体建议：**持有 / 止盈 / 补仓 / 止损**，并说明理由
- 注意：如果持有不足 7 天，必须强调惩罚性赎回费 1.5%

### 3️⃣ 操作计划
给出明日具体可执行的操作建议：
- 今日是否建议操作（15:00 前）
- 如果有操作，建议买/卖多少金额
- 后续关注的止盈/止损点位

## 回答原则

1. 保守优先：非明确机会不建议频繁操作
2. 数据说话：每个建议都要基于持仓数据
3. 风险提示：提醒基金投资风险和短期操作成本
4. 输出控制在 800 字以内，简洁直接
5. **不得建议追涨杀跌**
6. **不得保证收益**
"""


def get_api_key():
    """获取 DeepSeek API Key"""
    # 1. st.secrets（部署用）
    try:
        if "DEEPSEEK_API_KEY" in st.secrets:
            return st.secrets["DEEPSEEK_API_KEY"]
    except Exception:
        pass
    # 2. session_state（手动输入）
    return st.session_state.get("deepseek_api_key", "")


def has_api_key():
    """是否有可用的 API Key"""
    return bool(get_api_key())


def build_portfolio_context(holdings, estimates):
    """构建持仓上下文文本供 AI 分析"""
    lines = []
    lines.append(f"分析日期：{date.today().isoformat()}")
    lines.append(f"持仓数量：{len(holdings)} 只")
    lines.append("")

    total_cost = 0.0
    total_value = 0.0

    for _, row in holdings.iterrows():
        code = row["fund_code"]
        name = row["fund_name"]
        cost = float(row["buy_amount"])

        # 从缓存中取估值
        est = estimates.get(code, {})
        current_nav = est.get("estimate", 0) if est.get("success") else 0

        nav_at_buy = (
            row["nav_at_buy"]
            if pd.notna(row.get("nav_at_buy")) and row["nav_at_buy"]
            else 1.0
        )
        shares = row.get("shares")
        if pd.isna(shares) or not shares:
            shares = cost / nav_at_buy if nav_at_buy > 0 else 0

        current_value = float(shares) * current_nav if current_nav > 0 and shares > 0 else 0
        profit = current_value - cost
        profit_pct = (profit / cost * 100) if cost > 0 else 0

        total_cost += cost
        total_value += current_value

        hold_days = _calc_days(row["buy_date"])
        est_change = est.get("estimate_change", 0)
        fund_type = row.get("fund_type", "C")

        lines.append(f"基金：{name}（{code}）")
        lines.append(f"  类型：{fund_type}类")
        lines.append(f"  买入金额：{cost:.0f}元 | 买入日期：{row['buy_date']} | 持有 {hold_days} 天")
        lines.append(f"  参考净值：买入 {nav_at_buy:.4f} → 当前估算 {current_nav:.4f}（今日估值涨跌 {est_change:+.2f}%）")
        lines.append(f"  当前市值：{current_value:.0f}元 | 盈亏：{profit:+.0f}元（{profit_pct:+.2f}%）")
        target = row.get("target_return", 10)
        lines.append(f"  止盈目标：{target}%")
        lines.append("")

    # 组合概况
    total_profit = total_value - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
    lines.append(f"组合总投入：{total_cost:.0f}元")
    lines.append(f"组合总市值：{total_value:.0f}元")
    lines.append(f"组合总盈亏：{total_profit:+.0f}元（{total_profit_pct:+.2f}%）")

    return "\n".join(lines)


def _calc_days(buy_date_str):
    """计算持有天数"""
    try:
        buy = datetime.strptime(buy_date_str, "%Y-%m-%d").date()
        return (date.today() - buy).days
    except Exception:
        return 0


def generate_ai_advice(holdings_df, estimates_cache, api_key=None, model=DEFAULT_MODEL):
    """
    调用 DeepSeek 生成 AI 投资建议

    参数
    - holdings_df: 持仓 DataFrame
    - estimates_cache: dict[fund_code] -> estimate_result（由 app.py 的缓存提供）
    - api_key: DeepSeek API Key，None 则自动从 secrets/session_state 获取

    返回 (advice_text, error_message)
    """
    if holdings_df.empty:
        return None, "暂无持仓数据"

    if not api_key:
        api_key = get_api_key()
    if not api_key:
        return None, "未配置 DeepSeek API Key"

    # 构建上下文
    context = build_portfolio_context(holdings_df, estimates_cache)
    today = date.today().isoformat()

    user_prompt = (
        f"当前日期：{today}\n\n"
        f"以下是用户的基金持仓数据，请根据专业知识给出投资建议：\n\n"
        f"{context}\n\n"
        f"请结合当前市场环境分析，给出今日操作建议。"
    )

    try:
        client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

        with st.spinner("🤔 AI 正在分析持仓数据…（约 10-30 秒）"):
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=2500,
                timeout=60,
            )

        text = response.choices[0].message.content.strip()
        return text, None

    except Exception as e:
        return None, f"AI 分析请求失败：{str(e)}"
