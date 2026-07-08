"""
A股增强层 (enrichment) — 接入 a-stock-data / akshare 数据源，为异动个股补充「为什么动」的上下文。

数据来源:
  第一批 (稳定):
    - 东财 slist   → 个股所属板块/概念归属 (eastmoney_concept_blocks)
    - 东财 push2   → 个股资金流向 分钟级    (eastmoney_fund_flow_minute)
    - 东财 search  → 个股相关新闻          (eastmoney_stock_news)
  第二批 (龙虎榜 / 打板池 / 北向资金, 跑稳后再进卡片):
    - 东财 涨停股池 (akshare stock_zt_pool_em)        → 打板池: 连板数/封板资金/炸板次数
    - 东财 龙虎榜详情 (akshare stock_lhb_detail_em)    → 龙虎榜: 上榜原因/净买额/席位
    - 东财 沪深港通资金流 (akshare stock_hsgt_fund_flow_summary_em) → 北向资金: 沪/深股通净买额

设计原则:
  - 非阻塞: 任一接口失败只返回空结构，绝不抛异常影响主预警流程。
  - 防封: 第一批走 em_get() 串行限流；第二批走 akshare(已装依赖)，全局列表进程内只抓一次(缓存)。
  - 强制 IPv4: 沙箱/部分网络下 Python 会选 IPv6 导致连接 reset，统一强制 IPv4。
  - 仅对 A股 (6位代码) 调用，美股不进此模块。
  - akshare 惰性导入: 缺失时该子模块直接不可用，不影响其余。

对外暴露:
  enrich_stock(code: str, name: str | None = None) -> dict
  get_market_context() -> dict   # 北向资金等全局上下文(供通知头部使用)
"""

import os
import re
import json
import time
import random
import logging
import socket
from datetime import datetime, timedelta

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

# ── 东财防封: 全局节流 + 会话复用 (第一批资金流/板块/新闻 使用) ───────────────
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


# ── 北京日期 / 候选交易日 (龙虎榜/打板池 仅在交易日盘后有数据) ─────────────────
def _beijing_date_str():
    """返回北京时间今日 YYYYMMDD (中国无夏令时, 直接 +8)。"""
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y%m%d")

def _candidate_dates(n=5):
    """最近 n 天(含今天)日期列表, 用于回退到最近一个有数据的交易日。"""
    base = datetime.utcnow() + timedelta(hours=8)
    for i in range(n):
        yield (base - timedelta(days=i)).strftime("%Y%m%d")


# ── 模块级缓存: 全局列表一次运行只抓一次 (第二批) ─────────────────────────────
_ZT_POOL_CACHE = {}   # date -> list[dict]  (打板池全量)
_LHB_CACHE = {}       # date -> list[dict]  (龙虎榜全量)
_NORTHBOUND_CACHE = {"data": None}


# ── 配置 (可选, 缺省使用默认值) ────────────────────────────────────────────
def _load_enrich_config():
    cfg = {
        "enabled": True, "min_interval": 1.0, "news_limit": 3, "concept_limit": 8,
        "lhb": {"enabled": True}, "zt_pool": {"enabled": True}, "northbound": {"enabled": False},
    }
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        cfg_path = os.path.join(project_root, 'config', 'config.json')
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ec = data.get('enrichment', {})
            for k in ("enabled", "min_interval", "news_limit", "concept_limit"):
                if k in ec:
                    cfg[k] = ec[k]
            for sub in ("lhb", "zt_pool", "northbound"):
                if isinstance(ec.get(sub), dict):
                    cfg[sub] = {**cfg[sub], **ec[sub]}
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


def _rec_get(rec, *keys, default=None):
    """从记录里按多个候选 key 取值(东财/akshare 列名不统一时兜底)。"""
    if not isinstance(rec, dict):
        return default
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return default


def _yuan_to_wan(v):
    """元 → 万元 (None 透传)。"""
    try:
        return round(float(v) / 1e4, 1)
    except Exception:
        return None


def _yuan_to_yi(v):
    """元 → 亿元 (None 透传)。"""
    try:
        return round(float(v) / 1e8, 2)
    except Exception:
        return None


def _ak_retry(fn, attempts=3, sleep_base=0.8):
    """akshare 调用重试(缓解沙箱/盘中接口偶发 NoneType/连接抖动)。"""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < attempts - 1:
                time.sleep(sleep_base * (i + 1) + random.uniform(0, 0.3))
    raise last


def _secid(code):
    """东财 secid: 沪市 1.xxxxxx, 深市 0.xxxxxx。"""
    code = normalize_code(code)
    market = 1 if code.startswith(("6", "9")) else 0
    return f"{market}.{code}"


# ── 1. 板块/概念归属 (东财 slist) ───────────────────────────────────────────
def get_concept(code):
    """个股所属板块/概念归属 (东财 slist, 一次请求拿全)。"""
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
    """个股资金流向 (分钟级, 当日盘中)。单位: 接口返回元 → 万元。"""
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
    """东财个股新闻 (JSONP 接口)。返回: [{title, time, source}]。"""
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


# ── 4. 打板池 (东财 涨停股池, akshare) ──────────────────────────────────────
def get_zt_pool(code):
    """
    打板池(涨停股池)成员查询: 进程内只抓一次全量, 之后按代码查表。
    返回: {available, in_pool, name, change_pct, price, board_count(连板数),
           zt_stat(涨停统计), seal_cap_yi(封板资金/亿), first_seal, last_seal,
           open_times(炸板次数), industry}
    """
    code = normalize_code(code)
    out = {"available": False, "in_pool": False}
    try:
        import akshare as ak
        best = None
        for d in _candidate_dates():
            if d in _ZT_POOL_CACHE:
                if _ZT_POOL_CACHE[d]:   # 非空缓存优先
                    best = d
                    break
                continue                # 空缓存(如盘中打板池未生成) → 回退到最近交易日
            try:
                df = _ak_retry(lambda: ak.stock_zt_pool_em(date=d))
            except Exception as e:
                logging.warning(f"[ENRICH] 打板池抓取失败 {d}: {e}")
                df = None
            if df is not None and len(df):
                _ZT_POOL_CACHE[d] = df.to_dict(orient="records")
                best = d
                break
            _ZT_POOL_CACHE[d] = []   # 缓存空结果, 避免重复抓取
        if best is None:
            return out
        rec = next((r for r in _ZT_POOL_CACHE[best]
                    if normalize_code(_rec_get(r, "代码", "SECURITY_CODE", default="")) == code), None)
        out["available"] = True
        if rec:
            seal_yuan = _rec_get(rec, "封板资金", "BILLBOARD_SEAL_AMT")
            out.update({
                "in_pool": True,
                "name": _rec_get(rec, "名称", "SECURITY_NAME_ABBR"),
                "change_pct": _rec_get(rec, "涨跌幅", "CHANGE_RATE"),
                "price": _rec_get(rec, "最新价", "CLOSE_PRICE"),
                "board_count": _rec_get(rec, "连板数", "BILLBOARD_TIMES"),
                "zt_stat": _rec_get(rec, "涨停统计", "ZT_STAT"),
                "seal_cap_yi": _yuan_to_yi(seal_yuan),
                "first_seal": _rec_get(rec, "首次封板时间", "FIRST_TIME"),
                "last_seal": _rec_get(rec, "最后封板时间", "LAST_TIME"),
                "open_times": _rec_get(rec, "炸板次数", "OPEN_TIMES"),
                "industry": _rec_get(rec, "所属行业", "INDUSTRY"),
            })
    except ImportError:
        out["error"] = "akshare_missing"
    except Exception as e:
        logging.warning(f"[ENRICH] 打板池查询失败 {code}: {e}")
    return out


# ── 5. 龙虎榜 (东财 龙虎榜详情, akshare) ────────────────────────────────────
def get_lhb(code):
    """
    龙虎榜成员查询: 进程内只抓一次当日全量, 之后按代码查表。
    返回: {available, on_board, name, date, reason(上榜原因/解读),
           close, change_pct, net_wan(龙虎榜净买额/万), buy_wan, sell_wan, deal_wan}
    """
    code = normalize_code(code)
    out = {"available": False, "on_board": False}
    try:
        import akshare as ak
        best = None
        for d in _candidate_dates():
            if d in _LHB_CACHE:
                if _LHB_CACHE[d]:   # 非空缓存优先
                    best = d
                    break
                continue             # 空缓存(如盘中龙虎榜未公布) → 回退到最近交易日
            try:
                # stock_lhb_detail_em 底层用 RPT_DAILYBILLBOARD_DETAILSNEW, 单日即当日全量
                df = _ak_retry(lambda: ak.stock_lhb_detail_em(start_date=d, end_date=d))
            except Exception as e:
                logging.warning(f"[ENRICH] 龙虎榜抓取失败 {d}: {e}")
                df = None
            if df is not None and len(df):
                _LHB_CACHE[d] = df.to_dict(orient="records")
                best = d
                break
            _LHB_CACHE[d] = []
        if best is None:
            return out
        rec = next((r for r in _LHB_CACHE[best]
                    if normalize_code(_rec_get(r, "代码", "SECURITY_CODE", default="")) == code), None)
        out["available"] = True
        if rec:
            out.update({
                "on_board": True,
                "name": _rec_get(rec, "名称", "SECURITY_NAME_ABBR"),
                "date": _rec_get(rec, "上榜日", "TRADE_DATE"),
                "reason": _rec_get(rec, "上榜原因", "REASON", "解读", "EXPLAIN"),
                "explain": _rec_get(rec, "解读", "EXPLAIN"),
                "close": _rec_get(rec, "收盘价", "CLOSE_PRICE"),
                "change_pct": _rec_get(rec, "涨跌幅", "CHANGE_RATE"),
                "net_yi": _yuan_to_yi(_rec_get(rec, "龙虎榜净买额", "BILLBOARD_NET_AMT")),
                "buy_yi": _yuan_to_yi(_rec_get(rec, "龙虎榜买入额", "BILLBOARD_BUY_AMT")),
                "sell_yi": _yuan_to_yi(_rec_get(rec, "龙虎榜卖出额", "BILLBOARD_SELL_AMT")),
                "deal_yi": _yuan_to_yi(_rec_get(rec, "龙虎榜成交额", "BILLBOARD_DEAL_AMT")),
            })
    except ImportError:
        out["error"] = "akshare_missing"
    except Exception as e:
        logging.warning(f"[ENRICH] 龙虎榜查询失败 {code}: {e}")
    return out


# ── 6. 北向资金 (东财 沪深港通资金流, akshare) ─────────────────────────────
def get_northbound():
    """
    北向资金(沪深股通)当日净买额。进程内只抓一次。
    返回: {available, date, total_net_yi(成交净买额/亿), total_inflow_yi(资金净流入/亿),
           sh_net_yi(沪股通), sz_net_yi(深股通)}
    注意: 2024-08 起港交所盘中不再实时披露北向净额, 盘中多为 0, 收盘后回填真实值。
    """
    if _NORTHBOUND_CACHE["data"] is not None:
        return _NORTHBOUND_CACHE["data"]
    out = {"available": False}
    try:
        import akshare as ak
        df = ak.stock_hsgt_fund_flow_summary_em()
        nb = df[df["资金方向"] == "北向"]
        if len(nb):
            sh = nb[nb["板块"].astype(str).str.contains("沪股通")]["成交净买额"]
            sz = nb[nb["板块"].astype(str).str.contains("深股通")]["成交净买额"]
            out.update({
                "available": True,
                "date": str(_rec_get(nb.iloc[0].to_dict(), "交易日", default="")),
                "total_net_yi": round(float(nb["成交净买额"].sum()), 2),
                "total_inflow_yi": round(float(nb["资金净流入"].sum()), 2),
                "sh_net_yi": round(float(sh.sum()), 2) if len(sh) else None,
                "sz_net_yi": round(float(sz.sum()), 2) if len(sz) else None,
            })
        else:
            out["available"] = True  # 当日尚无北向数据(盘中/非交易日)
    except ImportError:
        out["error"] = "akshare_missing"
    except Exception as e:
        logging.warning(f"[ENRICH] 北向资金失败: {e}")
    _NORTHBOUND_CACHE["data"] = out
    return out


def get_market_context():
    """全局市场上下文(通知头部可用): 当前仅北向资金(2024-08 起盘中不再披露, 默认关闭)。"""
    cfg = _load_enrich_config()
    if cfg.get("northbound", {}).get("enabled", False):
        return {"northbound": get_northbound()}
    return {"northbound": {}}


# ── 聚合入口 ───────────────────────────────────────────────────────────────
def enrich_stock(code, name=None):
    """
    为单只 A股聚合 板块/资金流/新闻 + 打板池/龙虎榜 上下文。
    永不抛异常: 任一子模块失败仅该部分 available=False。
    返回结构:
    {
      "name", "fund_flow", "concept", "news",
      "zt_pool", "lhb", "northbound",
      "concept_limit", "error"
    }
    """
    cfg = _load_enrich_config()
    code = normalize_code(code)
    result = {
        "name": name,
        "fund_flow": {}, "concept": {}, "news": [],
        "zt_pool": {}, "lhb": {}, "northbound": {},
        "concept_limit": int(cfg.get("concept_limit", 8)),
        "error": None,
    }

    if not cfg.get("enabled", True):
        result["error"] = "disabled"
        return result
    if not code or len(code) != 6:
        result["error"] = "invalid_code"
        return result

    # 第一批 (东财直连, 自带限流)
    result["concept"] = get_concept(code)
    result["fund_flow"] = get_fund_flow(code)
    try:
        news_limit = int(cfg.get("news_limit", 3))
    except Exception:
        news_limit = 3
    result["news"] = get_news(code, page_size=max(news_limit, 5))[:news_limit]

    # 第二批 (akshare, 全局列表缓存)
    if cfg.get("zt_pool", {}).get("enabled", True):
        result["zt_pool"] = get_zt_pool(code)
    if cfg.get("lhb", {}).get("enabled", True):
        result["lhb"] = get_lhb(code)
    if cfg.get("northbound", {}).get("enabled", True):
        result["northbound"] = get_northbound()

    return result


if __name__ == "__main__":
    # 本地冒烟测试 (需联网)
    for c in ["600519", "000858", "002497"]:
        print(f"=== {c} ===")
        print(json.dumps(enrich_stock(c), ensure_ascii=False, indent=2))
    print("=== northbound ===")
    print(json.dumps(get_northbound(), ensure_ascii=False, indent=2))
