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

## 回答原则（必须遵守）

1. **保守优先**：非明确机会不建议频繁操作
2. **操作为主**：不要泛泛而谈市场，直接给出今日 15:00 前要不要操作、操作多少
3. **风险提示**：持有不足 7 天必须强调 1.5% 惩罚性赎回费
4. **输出控制在 800 字以内**，简洁直接
5. **不得建议追涨杀跌**
6. **不得保证收益**

## 输出格式

严格按照以下结构输出：

---

### 1️⃣ 操作速览

用表格列出每只基金今日的建议，格式如下：

| 基金 | 操作建议 | 操作金额 | 理由 |
|------|---------|---------|------|
| 东方人工智能混合C | 补仓 | +500~1000元 | 短期跌幅较大，可分批低吸 |
| 易方达人工智能ETF联接C | 持有 | — | 今日强势反弹，观望 |

操作建议仅限以下 4 种：**持有 / 补仓 / 止盈 / 止损**
- 操作金额填具体数字范围，不操作填 `—`

### 2⃣️ 逐只分析

每只基金独立一段，包含：
- **状态**：持有天数 · 盈亏比例 · 今日涨跌
- **判断**：当前处于什么阶段（建仓期/浅套/盈利），用一句话说清
- **操作逻辑**：今天为什么建议这样操作？基于什么判断？
  - 补仓 → 说明触发条件（如：跌幅超 X%、低于成本线 X%）
  - 止盈 → 说明目标收益率到了没有
  - 止损 → 说明止损理由和后续计划

### 3⃣️ 操作计划（今日）

- **今日是否操作**：建议在 15:00 前操作 / 建议不动
- **优先级**：如果资金有限，优先操作哪只？为什么？
- **仓位建议**：当前总仓位占计划投入的比例建议（如：建议总仓位控制在 60%~70%）

### 4️⃣ 后续关注

- 每只基金的**止盈目标**和**止损线**（具体数字）
- 什么情况下需要调整计划（如：连续三日涨幅超 5% 需重新评估）"""


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
        f"分析要点：\n"
        f"1. 判断每只基金当前处于什么状态（盈利/浅套/深套/刚建仓）\n"
        f"2. 结合今日估值涨跌，判断是补仓摊薄成本的机会，还是应该止盈\n"
        f"3. 考虑持有天数，不足 7 天必须提醒赎回费\n"
        f"4. 如果建议补仓，给出具体金额范围\n"
        f"5. 如果建议持有，说明在等什么信号\n\n"
        f"请严格按照系统指令的格式输出。"
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
                temperature=0.5,
                max_tokens=3000,
                timeout=90,
            )

        text = response.choices[0].message.content.strip()
        return text, None

    except Exception as e:
        return None, f"AI 分析请求失败：{str(e)}"
