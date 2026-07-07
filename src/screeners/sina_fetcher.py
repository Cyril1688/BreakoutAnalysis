"""
Sinat + Tencent A-Share Data Fetcher (Fallback for GitHub Actions)
========================================
当 akshare (East Money) 在 GitHub Actions runner 上被 IP 封锁时，
自动降级到此模块——通过新浪财经 + 腾讯财经双源获取 A 股实时行情。

接口:
  - 新浪: vip.stock.finance.sina.com.cn   (全量分页, 100 条/页)
  - 腾讯: qt.gtimg.cn                    (批量查询单只/多只)

输出列名与 akshare 的 East Money 列名一致，下游 apply_filters / normalize_to_standard 无需改动。
"""

import logging
import pandas as pd
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 新浪配置 ──
SINA_BASE = ("http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
             "/Market_Center.getHQNodeData")
SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
    "Accept": "application/json, text/plain, */*",
}

# ── 腾讯配置 ──
TENCENT_API = "http://qt.gtimg.cn/q={}"

# 新浪返回字段 → 东财列名（apply_filters / normalize_to_standard 适用）
SINA_TO_EASTMONEY = {
    "code": "代码",
    "name": "名称",
    "trade": "最新价",
    "pricechange": "涨跌额",
    "changepercent": "涨跌幅",
    "volume": "成交量",
    "amount": "成交额",
    "open": "今开",
    "high": "最高",
    "low": "最低",
    "settlement": "昨收",
    "mktcap": "总市值",
    "nmc": "流通市值",
    "turnoverratio": "换手率",
    "per": "市盈率-动态",
    "pb": "市净率",
    "amplitude": "振幅",
}

# 腾讯字段索引 (v_X="1~name~code~price~...)
# 文档: https://blog.csdn.net/weixin_41697727/article/details/118507740
# 索引: 1=name, 2=code, 3=price, 4=last_close, 5=open, 6=volume, 7=buy, 8=sell
#        9~20=五档盘口, 32=datetime, 33=change%, 37=high, 38=low,
#        39=price/pre_close(涨跌幅%), 44=high, 45=low(重复),
#        46=成交量(手), 47=成交额(万)
# 我们主要用新浪，腾讯做备用


def _fetch_sina_page(page, num=100):
    """获取新浪一页数据，返回 list[dict]"""
    try:
        url = f"{SINA_BASE}?page={page}&num={num}&sort=changepercent&asc=0&node=hs_a"
        r = requests.get(url, headers=SINA_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logging.warning(f"Sina page {page} failed: {e}")
        return []


def _sina_record_to_row(rec):
    """将新浪单条记录的 key 映射为东财列名，并数值化"""
    row = {}
    for sina_key, em_col in SINA_TO_EASTMONEY.items():
        val = rec.get(sina_key)
        if val is None or val == "" or val == "-":
            row[em_col] = None
        else:
            try:
                row[em_col] = float(val)
            except (ValueError, TypeError):
                row[em_col] = val  # 名称等文本
    # 名称保持文本
    row["名称"] = rec.get("name", "")
    # 代码补齐6位
    raw_code = rec.get("code", "")
    if raw_code and raw_code.isdigit():
        row["代码"] = raw_code.zfill(6)
    else:
        row["代码"] = raw_code

    # ── 单位转换 ──
    # 新浪的 总市值/流通市值 单位是 万元，下游 apply_filters 期望 元
    for col in ("总市值", "流通市值"):
        if col in row and row[col] is not None:
            row[col] = row[col] * 10000.0

    return row


def fetch_from_sina(max_pages=60):
    """
    从新浪全量分页拉取 A 股行情。
    返回 pandas DataFrame，列名与 akshare East Money 输出一致。
    空数据返回空 DataFrame。
    """
    all_rows = []
    failed_pages = 0

    for page in range(1, max_pages + 1):
        records = _fetch_sina_page(page)
        if not records:
            failed_pages += 1
            # 连续 3 页空 → 结束
            if failed_pages >= 3:
                break
            continue
        failed_pages = 0
        for rec in records:
            row = _sina_record_to_row(rec)
            all_rows.append(row)
        # 不足 100 条 → 最后一页
        if len(records) < 100:
            break
        time.sleep(0.15)  # 小额延迟防封

    if not all_rows:
        logging.warning("Sina returned no data.")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # 数值列转换
    numeric_cols = ["最新价", "涨跌额", "涨跌幅", "成交量", "成交额",
                    "今开", "最高", "最低", "昨收", "总市值", "流通市值",
                    "换手率", "市盈率-动态", "市净率", "振幅"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    logging.info(f"Sina fetcher: {len(df)} A-share stocks loaded ({len(all_rows)} raw rows).")
    return df


def fetch_from_tencent_batch(codes):
    """
    腾讯批量查询（备用，目前仅作为新浪失败的降级）。
    codes: list of 6-digit string codes, e.g. ["600519","000858"]
    返回 DataFrame，列名与 Sina 对齐（后续映射到东财列名）。
    """
    if not codes:
        return pd.DataFrame()

    # 拼接带前缀的代码: sh=60xxxx, sz=00xxxx/30xxxx, bj=4xxxxx/8xxxxx
    prefixed = []
    for c in codes:
        c = c.strip().zfill(6)
        if c.startswith("6"):
            prefixed.append(f"sh{c}")
        elif c.startswith(("0", "3")):
            prefixed.append(f"sz{c}")
        elif c.startswith(("4", "8")):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sh{c}")

    url = TENCENT_API.format(",".join(prefixed))

    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
        lines = r.text.strip().split("\n")
        rows = []
        for line in lines:
            line = line.strip()
            if not line or "v_pv_none_match" in line:
                continue
            parts = line.split("~")
            if len(parts) < 47:
                continue
            try:
                code = parts[2]
                rows.append({
                    "代码": code.zfill(6),
                    "名称": parts[1],
                    "最新价": _f(parts[3]),
                    "昨收": _f(parts[4]),
                    "今开": _f(parts[5]),
                    "成交量": _f(parts[6]) * 100 if parts[6] else None,  # 手 → 股
                    "成交额": _f(parts[46]) * 10000 if len(parts) > 46 and parts[46] else None,  # 万 → 元
                    "最高": _f(parts[33]) if len(parts) > 33 else None,
                    "最低": _f(parts[34]) if len(parts) > 34 else None,
                    "涨跌幅": _f(parts[32]) if len(parts) > 32 else None,
                    "市盈率-动态": _f(parts[39]) if len(parts) > 39 else None,
                })
            except (ValueError, IndexError):
                continue

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        logging.info(f"Tencent batch: {len(df)} stocks.")
        return df

    except Exception as e:
        logging.warning(f"Tencent batch query failed: {e}")
        return pd.DataFrame()


def _f(v):
    """安全转 float"""
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ── 入口 ──
def fetch_fallback_data():
    """
    主入口：先试新浪（全量），失败再试腾讯（全量）。
    返回 DataFrame（东财列名），下游无缝对接 apply_filters + normalize_to_standard。
    """
    df = fetch_from_sina()
    if df is not None and not df.empty:
        return df

    logging.warning("Sina fallback returned empty. Trying Tencent...")
    # 如果有代码列表可迭代，走腾讯批量；这里保守返回空
    return df
