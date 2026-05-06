"""
基金数据获取模块 - 基于天天基金(东方财富)公开API
"""
import json
import re
import time
from datetime import datetime, date, time as dtime

import pandas as pd
import requests

# ============== HTTP 配置 ==============
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Referer': 'https://fund.eastmoney.com/',
}

REQUEST_TIMEOUT = 15  # 单次请求超时
MAX_RETRIES = 2       # 最大重试次数


def _http_get(url, params=None):
    """带重试的 HTTP GET 请求"""
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.encoding = 'utf-8'
            return resp.text
        except requests.RequestException as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                time.sleep(1)
    raise last_exc


# ============== 基金数据接口 ==============

def get_fund_estimate(fund_code):
    """
    获取基金盘中实时估值
    返回: {
        'success': bool,
        'code': str,
        'name': str,
        'estimate': float,       # 估算净值
        'estimate_change': float, # 估算涨跌幅(%)
        'net_value': float,      # 最新公布净值
        'date': str,             # 数据时间
    }
    """
    url = f'https://fundgz.1234567.com.cn/js/{fund_code}.js'
    try:
        text = _http_get(url)
        match = re.search(r'jsonpgz\((.+)\)', text)
        if not match:
            return _empty_estimate(fund_code, "无法解析估值数据")

        data = json.loads(match.group(1))
        return {
            'success': True,
            'code': str(data.get('fundcode', fund_code)),
            'name': str(data.get('name', '')),
            'estimate': _safe_float(data.get('gsz', 0)),
            'estimate_change': _safe_float(data.get('gszzl', 0)),
            'net_value': _safe_float(data.get('dwjz', 0)),
            'date': str(data.get('gztime', '')),
        }
    except Exception:
        return _empty_estimate(fund_code, "网络异常，可稍后重试")


def get_fund_name(fund_code):
    """获取基金名称"""
    # 优先从估值接口取（更快，不用额外请求）
    est = get_fund_estimate(fund_code)
    if est['success'] and est['name']:
        return est['name']

    # fallback: 天天基金基础信息 API
    url = 'https://api.fund.eastmoney.com/f10/FundBasicInfo'
    try:
        text = _http_get(url, params={'fundCode': fund_code})
        data = json.loads(text)
        name = data.get('Data', {}).get('NAME', '')
        if name:
            return name
    except Exception:
        pass

    return fund_code


def get_fund_nav_history(fund_code, days=365):
    """
    获取基金历史净值
    返回 DataFrame，列：日期, 单位净值, 累计净值
    """
    url = 'https://api.fund.eastmoney.com/f10/lsjz'
    params = {
        'fundCode': fund_code,
        'pageIndex': 1,
        'pageSize': days,
    }
    try:
        text = _http_get(url, params=params)
        match = re.search(r'jQuery[0-9]+\((.+)\)', text)
        if not match:
            # 部分接口可能直接返回 JSON
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return pd.DataFrame()
        else:
            data = json.loads(match.group(1))

        records = data.get('Data', {}).get('LSJZList', [])
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df = df.rename(columns={
            'FSRQ': '日期',
            'DWJZ': '单位净值',
            'LJJZ': '累计净值',
        })
        df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
        df['单位净值'] = pd.to_numeric(df['单位净值'], errors='coerce')
        df = df.dropna(subset=['日期', '单位净值'])
        df = df.sort_values('日期').reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


# ============== 交易时间工具 ==============

# 中国法定假日（每年需更新，此处列出近两年主要假日）
# 格式: (月, 日)
_CN_HOLIDAYS = None


def _get_cn_holidays():
    """获取中国股市假日集合（返回 (month, day) 元组集合）"""
    global _CN_HOLIDAYS
    if _CN_HOLIDAYS is not None:
        return _CN_HOLIDAYS

    # 2025-2026 年主要 A 股休市日（月, 日）
    holidays = {
        # 2025 年
        (1, 1),   # 元旦
        (1, 28), (1, 29), (1, 30), (1, 31),  # 春节
        (2, 3), (2, 4),
        (4, 4), (4, 5),   # 清明节
        (5, 1), (5, 2), (5, 5),   # 劳动节
        (5, 31), (6, 2), (6, 3),  # 端午节
        (10, 1), (10, 2), (10, 3), (10, 6), (10, 7), (10, 8),  # 国庆
        # 2026 年
        (1, 1), (1, 2),
        (2, 16), (2, 17), (2, 18), (2, 19), (2, 20),  # 春节
        (4, 4), (4, 5), (4, 6),
        (5, 1), (5, 4), (5, 5),
        (6, 19), (6, 22),
        (10, 1), (10, 2), (10, 5), (10, 6), (10, 7), (10, 8),
    }
    _CN_HOLIDAYS = holidays
    return holidays


def is_trading_day(dt=None):
    """判断是否为交易日（周一至周五，非节假日）"""
    if dt is None:
        dt = date.today()
    elif isinstance(dt, datetime):
        dt = dt.date()

    if dt.weekday() >= 5:  # 周六日
        return False

    holidays = _get_cn_holidays()
    if (dt.month, dt.day) in holidays:
        return False

    # 调休补班（每年需更新）
    makeup_workdays = {
        (2025, 1, 26), (2025, 2, 8),    # 春节调休
        (2025, 4, 27),                   # 劳动节调休
        (2025, 9, 28), (2025, 10, 11),    # 国庆调休
        (2026, 1, 24), (2026, 2, 14),    # 春节调休
        (2026, 4, 26), (2026, 5, 9),     # 劳动节调休
        (2026, 9, 27), (2026, 10, 10),   # 国庆调休
    }
    if (dt.year, dt.month, dt.day) in makeup_workdays:
        return True

    return True


def is_trading_time(dt=None):
    """判断是否为交易时间（9:30-15:00）"""
    if dt is None:
        dt = datetime.now()
    t = dt.time()
    return dtime(9, 30) <= t <= dtime(15, 0)


def get_30_min_warning(dt=None):
    """判断是否在 14:25-14:35 的提醒窗口"""
    if dt is None:
        dt = datetime.now()
    t = dt.time()
    return dtime(14, 25) <= t <= dtime(14, 35)


def calculate_holding_days(buy_date_str):
    """
    计算持仓天数
    买入当天不算，从下一个交易日开始计算
    """
    try:
        buy_date = pd.to_datetime(buy_date_str).date()
        return (date.today() - buy_date).days
    except Exception:
        return 0


# ============== 格式化工具 ==============

def format_change_pct(change):
    """格式化涨跌幅（返回带颜色的 HTML 字符串）"""
    if change > 0:
        return f'<span class="fund-up">▲ +{change:.2f}%</span>'
    elif change < 0:
        return f'<span class="fund-down">▼ {change:.2f}%</span>'
    else:
        return '<span>0.00%</span>'


def _safe_float(val, default=0.0):
    """安全转换为浮点数"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _empty_estimate(fund_code, reason=""):
    """返回空的估值结果"""
    return {
        'success': False,
        'code': fund_code,
        'name': fund_code,
        'estimate': 0.0,
        'estimate_change': 0.0,
        'net_value': 0.0,
        'date': '',
        'error': reason,
    }
