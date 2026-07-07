"""
A股增强层 (enrichment) — 接入 a-stock-data 数据源，为异动个股补充「为什么动」的上下文。

数据来源 (全部来自 simonlin1212/a-stock-data, Apache-2.0):
  - 东财 slist   → 个股所属板块/概念归属 (eastmoney_concept_blocks)
  - 东财 push2   → 个股资金流向 分钟级    (eastmoney_fund_flow_minute)
  - 东财 search  → 个股相关新闻          (eastmoney_stock_news)

设计原则:
  - 非阻塞: 任一接口失败只返回空结构，绝不抛异常影响主预警流程。
  - 防封: 所有东财请求走 em_get() 串行限流 (间隔≥1s + 随机抖动) + 会话复用。
  - 强制 IPv4: 沙箱/部分网络下 Python 会选 IPv6 导致连接 reset，统一强制 IPv4。
  - 仅对 A股 (6位代码) 调用，美股不进此模块。

对外暴露:
  enrich_stock(code: str, name: str | None = None) -> dict
"""

import os
import re
import json
import time
import random
import logging
import socket

# ── 强制 IPv4 (避免沙箱 IPv6 路由不可达导致 East Money 连接 reset) ──────────
_orig_getaddrinfo = socket.getaddrinfo
def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _getaddrinfo_ipv4
try:
    import urllib3.util.connection as _uc
    _uc.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

import requests  # noqa: E402  (放在 IPv4 补丁之后)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - ENRICH - %(levelname)s - %(message)s')

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── 东财防封: 全局节流 + 会话复用 ──────────────────────────────────────────
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": _UA})
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _em_adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _em_adapter)
    EM_SESSION.mount("http://", _em_adapter)
except Exception:
    pass
EM_MIN_INTERVAL = 1.0     # 两次东财请求最小间隔(秒)
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求入口: 自动节流 + 复用 session + 默认 UA。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


# ── 配置 (可选, 缺省使用默认值) ────────────────────────────────────────────
def _load_enrich_config():
    cfg = {"enabled": True, "min_interval": 1.0, "news_limit": 3, "concept_limit": 8}
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        cfg_path = os.path.join(project_root, 'config', 'config.json')
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ec = data.get('enrichment', {})
            cfg.update({k: ec[k] for k in cfg if k in ec})
    except Exception:
        pass
    return cfg


def normalize_code(code):
    """6位代码归一化: 去除 SH/SZ/市场前缀/后缀, 取纯数字。"""
    if not code:
        return ""
    s = str(code).strip().upper()
    s = re.sub(r'^(SH|SZ|BJ)\.?', '', s)
    s = re.sub(r'\.(SH|SZ|BJ)$', '', s)
    s = re.sub(r'[^0-9]', '', s)
    return s


def _secid(code):
    """东财 secid: 沪市 1.xxxxxx, 深市 0.xxxxxx。"""
    code = normalize_code(code)
    market = 1 if code.startswith(("6", "9")) else 0
    return f"{market}.{code}"


# ── 1. 板块/概念归属 (东财 slist) ───────────────────────────────────────────
def get_concept(code):
    """
    个股所属板块/概念归属 (东财 slist, 一次请求拿全)。
    返回: {available, total, tags:[板块名...], boards:[{name,code,change_pct,lead_stock}]}
    """
    code = normalize_code(code)
    out = {"available": False, "total": 0, "tags": [], "boards": []}
    try:
        market_code = 1 if code.startswith(("6", "9")) else 0
        params = {
            "fltt": "2", "invt": "2",
            "secid": f"{market_code}.{code}",
            "spt": "3", "pi": "0", "pz": "200", "po": "1",
            "fields": "f12,f14,f3,f128",
        }
        headers = {"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"}
        r = em_get("https://push2.eastmoney.com/api/qt/slist/get",
                   params=params, headers=headers, timeout=15)
        d = r.json()
        diff = (d.get("data") or {}).get("diff") or {}
        items = diff.values() if isinstance(diff, dict) else diff
        boards = []
        for it in items:
            boards.append({
                "name": it.get("f14", ""),
                "code": it.get("f12", ""),
                "change_pct": it.get("f3", ""),
                "lead_stock": it.get("f128", ""),
            })
        out["boards"] = boards
        out["tags"] = [b["name"] for b in boards if b["name"]]
        out["total"] = len(boards)
        out["available"] = True
    except Exception as e:
        logging.warning(f"[ENRICH] 板块归属请求失败 {code}: {e}")
    return out


# ── 2. 资金流向 分钟级 (东财 push2) ─────────────────────────────────────────
def get_fund_flow(code):
    """
    个股资金流向 (分钟级, 当日盘中)。
    返回: {available, main_net_today_wan(万元), signal(bullish/bearish), latest_time}
    单位换算: 接口返回元 → 万元 (/1e4)
    """
    code = normalize_code(code)
    out = {"available": False, "main_net_today_wan": None, "signal": None, "latest_time": None}
    try:
        secid = _secid(code)
        url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
        params = {
            "secid": secid, "klt": 1,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://quote.eastmoney.com/",
            "Origin": "https://quote.eastmoney.com",
        }
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        rows = []
        for line in d.get("data", {}).get("klines", []):
            parts = line.split(",")
            if len(parts) >= 6:
                rows.append({
                    "time": parts[0],
                    "main_net": float(parts[1]),
                    "small_net": float(parts[2]),
                    "mid_net": float(parts[3]),
                    "large_net": float(parts[4]),
                    "super_net": float(parts[5]),
                })
        if rows:
            last = rows[-1]
            total_yuan = sum(x["main_net"] for x in rows)
            out["main_net_today_wan"] = round(total_yuan / 1e4, 1)
            out["signal"] = "bullish" if last["main_net"] > 0 else "bearish"
            out["latest_time"] = last["time"]
            out["available"] = True
    except Exception as e:
        logging.warning(f"[ENRICH] 资金流请求失败 {code}: {e}")
    return out


# ── 3. 个股新闻 (东财 search-api-web JSONP) ─────────────────────────────────
def get_news(code, page_size=10):
    """
    东财个股新闻 (JSONP 接口)。
    返回: [{title, time, source}]  (最多 page_size 条, 调用方自行截断)
    """
    code = normalize_code(code)
    out = []
    try:
        cb = "jQuery_news"
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        inner_params = json.dumps({
            "uid": "",
            "keyword": code,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                      "pageIndex": 1, "pageSize": page_size, "preTag": "", "postTag": ""}},
        }, separators=(',', ':'))
        params = {"cb": cb, "param": inner_params}
        headers = {"User-Agent": _UA, "Referer": "https://so.eastmoney.com/"}
        r = em_get(url, params=params, headers=headers, timeout=15)

        text = r.text
        json_str = text[text.index("(") + 1: text.rindex(")")]
        d = json.loads(json_str)
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
        for a in articles:
            out.append({
                "title": re.sub(r'<[^>]+>', '', a.get("title", "")),
                "time": a.get("date", ""),
                "source": a.get("mediaName", ""),
            })
    except Exception as e:
        logging.warning(f"[ENRICH] 新闻请求失败 {code}: {e}")
    return out


# ── 聚合入口 ───────────────────────────────────────────────────────────────
def enrich_stock(code, name=None):
    """
    为单只 A股聚合 板块/资金流/新闻 上下文。
    永不抛异常: 任一子模块失败仅该部分 available=False。
    返回结构:
    {
      "name": str|None,
      "fund_flow": {...},
      "concept": {...},
      "news": [...],
      "error": None
    }
    """
    cfg = _load_enrich_config()
    code = normalize_code(code)
    result = {"name": name, "fund_flow": {}, "concept": {}, "news": [], "error": None,
              "concept_limit": int(cfg.get("concept_limit", 8))}

    if not cfg.get("enabled", True):
        result["error"] = "disabled"
        return result
    if not code or len(code) != 6:
        result["error"] = "invalid_code"
        return result

    # 顺序调用, 各子模块自带异常保护
    result["concept"] = get_concept(code)
    result["fund_flow"] = get_fund_flow(code)
    try:
        news_limit = int(cfg.get("news_limit", 3))
    except Exception:
        news_limit = 3
    result["news"] = get_news(code, page_size=max(news_limit, 5))[:news_limit]
    return result


if __name__ == "__main__":
    # 本地冒烟测试 (需联网)
    for c in ["600519", "000858"]:
        print(f"=== {c} ===")
        print(json.dumps(enrich_stock(c), ensure_ascii=False, indent=2))
