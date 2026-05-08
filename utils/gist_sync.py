"""
GitHub Gist 远程同步模块

实现基金数据在 Gist 上的自动备份与恢复。
用户需提供：
1. GitHub Personal Access Token (经典版, 勾选 gist 权限)
2. Gist ID (首次自动创建)
"""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

GIST_API = "https://api.github.com/gists"

# Gist 内文件名
HOLDINGS_FILENAME = "fund_holdings.json"
WATCHLIST_FILENAME = "fund_watchlist.json"


def _build_headers(token):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "fund-manager-app",
    }


def _request(url, method="GET", headers=None, data=None):
    """底层 HTTP 请求"""
    req = Request(url, method=method, headers=headers or {})
    if data is not None:
        req.data = json.dumps(data).encode("utf-8")
    try:
        with urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return {"_error": f"HTTP {e.code}: {detail}"}
    except URLError as e:
        return {"_error": f"网络错误: {e.reason}"}
    except Exception as e:
        return {"_error": str(e)}


# ========== 公共接口 ==========


def test_connection(token):
    """验证 Token 是否有效"""
    result = _request(
        "https://api.github.com/user",
        headers=_build_headers(token),
    )
    return "login" in result, result.get("login", "")


def load_from_gist(token, gist_id):
    """
    从 Gist 读取持仓和关注数据
    返回 (holdings_list, watchlist_list) 或 (None, None)
    """
    url = f"{GIST_API}/{gist_id}"
    result = _request(url, headers=_build_headers(token))
    if "_error" in result:
        return None, None, result["_error"]

    files = result.get("files", {})

    holdings = _read_file_content(files.get(HOLDINGS_FILENAME))
    watchlist = _read_file_content(files.get(WATCHLIST_FILENAME))

    return (holdings or []), (watchlist or []), None


def save_to_gist(token, gist_id, holdings, watchlist):
    """
    将数据同步到 Gist
    holdings / watchlist 应传入列表(records)
    返回 (成功bool, 消息str)
    """
    files = {}
    files[HOLDINGS_FILENAME] = {
        "content": json.dumps(holdings, ensure_ascii=False, indent=2)
    }
    files[WATCHLIST_FILENAME] = {
        "content": json.dumps(watchlist, ensure_ascii=False, indent=2)
    }

    url = f"{GIST_API}/{gist_id}"
    result = _request(
        url,
        method="PATCH",
        headers=_build_headers(token),
        data={"files": files},
    )
    if "_error" in result:
        return False, result["_error"]
    return True, "同步成功"


def create_gist(token, holdings=None, watchlist=None):
    """
    创建新的 Gist（首次使用）
    返回 (gist_id, error_msg)
    """
    files = {}
    files[HOLDINGS_FILENAME] = {
        "content": json.dumps(holdings or [], ensure_ascii=False, indent=2)
    }
    files[WATCHLIST_FILENAME] = {
        "content": json.dumps(watchlist or [], ensure_ascii=False, indent=2)
    }

    result = _request(
        GIST_API,
        method="POST",
        headers=_build_headers(token),
        data={
            "description": "基金智管家 - 持仓数据自动备份",
            "public": False,
            "files": files,
        },
    )
    if "_error" in result:
        return None, result["_error"]
    gist_id = result.get("id")
    if not gist_id:
        return None, "创建 Gist 失败: 未返回 ID"
    return gist_id, None


# ========== 内部工具 ==========


def _read_file_content(file_obj):
    """从 Gist 文件对象中提取 JSON 内容"""
    if file_obj is None:
        return None
    raw = file_obj.get("content")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
