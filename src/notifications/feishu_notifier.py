"""
飞书 (Feishu/Lark) 通知模块
通过飞书机器人 Webhook 发送股票异动通知（卡片消息格式）
"""

import json
import logging
import os
from datetime import datetime, timezone

# 惰性导入 requests（避免在标准库 email.errors 不可用时阻塞导入）
_requests = None
def _get_requests():
    global _requests
    if _requests is None:
        import requests as _requests
    return _requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - FEISHU - %(levelname)s - %(message)s')

# 飞书卡片颜色模板
FEISHU_COLORS = {
    'us_up': 'blue',      # 美股上涨 → 蓝色
    'us_down': 'green',   # 美股下跌 → 绿色
    'china_up': 'red',    # A股上涨 → 红色 (中国惯例)
    'china_down': 'green', # A股下跌 → 绿色
    'briefing': 'purple',  # 市场简报 → 紫色
    'default': 'grey',
}

def load_config(config_path='config/config.json'):
    """加载飞书 Webhook 配置（优先从 config.json，其次环境变量 FEISHU_WEBHOOK_URL）"""
    # 检查环境变量（支持 GitHub Actions 部署）
    env_webhook = os.environ.get('FEISHU_WEBHOOK_URL', '')
    if env_webhook:
        logging.info("使用环境变量 FEISHU_WEBHOOK_URL")
        return {'webhook_url': env_webhook}

    # 从配置文件读取
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        config_file = os.path.join(project_root, config_path)
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        feishu_config = config.get('feishu', {})
        webhook_url = feishu_config.get('webhook_url', '')
        if not webhook_url or webhook_url == 'YOUR_FEISHU_WEBHOOK_URL':
            logging.warning("飞书 Webhook URL 未配置，请在 config.json 中设置 feishu.webhook_url 或设置 FEISHU_WEBHOOK_URL 环境变量")
            return None
        return feishu_config
    except Exception as e:
        logging.error(f"加载飞书配置失败: {e}")
        return None


# 中继转发地址（可选）。当 GitHub Actions 美国节点无法直接访问 open.feishu.cn 时，
# 可把请求发到一个能访问飞书的中继服务（如 Cloudflare Worker），由它转发给飞书。
# 设置 FEISHU_RELAY_URL 环境变量即自动启用，调用方无需改动。
RELAY_URL = os.environ.get('FEISHU_RELAY_URL', '').strip()


def _resolve_target(webhook_url):
    """如果有配置中继地址，则发往中继；否则直发飞书。"""
    if RELAY_URL:
        return RELAY_URL, True
    return webhook_url, False


def send_feishu_card(webhook_url, title, content_lines, color='blue'):
    """
    发送飞书交互式卡片消息

    Args:
        webhook_url: 飞书 Webhook URL（若设置了 FEISHU_RELAY_URL 则本参数被忽略，自动走中继）
        title: 卡片标题
        content_lines: 内容行列表，每行为 markdown 字符串
        color: 卡片主题色 (blue/red/green/purple/grey)
    """
    if not webhook_url and not RELAY_URL:
        logging.error("飞书 Webhook URL 为空")
        return False

    # 构建内容（支持 lark_md 格式）
    content_md = "\n".join(content_lines)

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": content_md}
            },
            {
                "tag": "hr"
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"BreakoutAnalysis 自动监控 | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                    }
                ]
            }
        ]
    }

    payload = {
        "msg_type": "interactive",
        "card": card
    }

    target, via_relay = _resolve_target(webhook_url)
    try:
        resp = _get_requests().post(target, json=payload, timeout=20)
        resp.raise_for_status()
        try:
            result = resp.json()
        except Exception:
            # 响应不是合法 JSON（常见于被网络中间层拦截返回的 HTML 错误页）
            body_preview = resp.text[:800] if hasattr(resp, 'text') else ''
            logging.error(
                f"飞书响应非 JSON (HTTP {resp.status_code}, via_relay={via_relay}): "
                f"{body_preview!r}"
            )
            return False
        if result.get('code') == 0:
            logging.info(f"飞书卡片发送成功: {title} (via_relay={via_relay})")
            return True
        else:
            logging.error(f"飞书 API 返回错误: {result}")
            return False
    except _get_requests().exceptions.RequestException as e:
        logging.error(f"飞书 Webhook 请求失败 (via_relay={via_relay}): {e}")
        return False
    except Exception as e:
        logging.error(f"飞书发送异常 (via_relay={via_relay}): {e}")
        return False




def format_stock_card(stock_data):
    """
    将股票通知数据格式化为飞书卡片内容
    返回 (title, content_lines, color)
    """
    ticker = stock_data.get('ticker', 'N/A')
    company = stock_data.get('company_name', 'N/A')
    market = stock_data.get('market', 'us')

    # 市场标签
    market_tag = "🇨🇳 A股" if market == 'china' else "🇺🇸 美股"
    title = f"{market_tag} {ticker} {company}"

    # 颜色
    change_str = stock_data.get('core_data_str', '')
    color = FEISHU_COLORS['china_up'] if market == 'china' else FEISHU_COLORS['us_up']

    lines = []

    # --- 核心数据 ---
    core = stock_data.get('core_data_str', '')
    if core and core != 'N/A':
        lines.append(f"**📊 核心数据**\n{core}")

    # --- 技术指标 ---
    tech = stock_data.get('technicals_str', '')
    if tech and tech != 'N/A':
        lines.append(f"\n**📈 技术指标**\n{tech}")

    # --- AI 分析 ---
    ai = stock_data.get('llm_analysis_str', '')
    if ai and ai != 'LLM analysis skipped (client not available).' and not ai.startswith('Error'):
        lines.append(f"\n**🤖 AI 分析**\n{ai}")

    # --- 新闻 ---
    news = stock_data.get('news_str', '')
    if news and news != 'No recent news found.':
        lines.append(f"\n**📰 相关新闻**\n{news}")

    # --- A股增强层 (板块/资金流/东财资讯, 非阻塞) ---
    enrich = stock_data.get('enrich')
    if market == 'china' and enrich and isinstance(enrich, dict):
        # 资金流
        ff = enrich.get('fund_flow') or {}
        if ff.get('available'):
            wan = ff.get('main_net_today_wan')
            sig = ff.get('signal')
            emoji = "🔴" if sig == 'bullish' else ("🟢" if sig == 'bearish' else "⚪")
            if sig == 'bullish':
                label = "主力净流入"
            elif sig == 'bearish':
                label = "主力净流出"
            else:
                label = "主力净额"
            flow_txt = f"{emoji} {label} **{wan}万**" if wan is not None else f"{emoji} {label} **N/A**"
            if ff.get('latest_time'):
                flow_txt += f"  (截至 {ff['latest_time']})"
            lines.append(f"\n**💰 资金流向**\n{flow_txt}")

        # 板块/概念
        concept = enrich.get('concept') or {}
        if concept.get('available') and concept.get('tags'):
            try:
                limit = int(enrich.get('concept_limit', 8))
            except Exception:
                limit = 8
            tags = concept['tags'][:limit]
            lines.append(f"\n**🏷️ 所属板块**\n{' · '.join(tags)}")

        # 东财资讯
        enews = enrich.get('news') or []
        if enews:
            news_lines = []
            for n in enews[:3]:
                t = n.get('time', '')
                src = n.get('source', '')
                head = f"**- {n.get('title', 'N/A')}**"
                tail = f" ({t}{(' | ' + src) if src else ''})" if t or src else ""
                news_lines.append(head + tail)
            lines.append(f"\n**📰 东财资讯**\n" + "\n".join(news_lines))

        # 打板池 (涨停股池成员)
        ztp = enrich.get('zt_pool') or {}
        if ztp.get('in_pool'):
            bc = ztp.get('board_count') or '?'
            ztstat = ztp.get('zt_stat') or '-'
            seal = ztp.get('seal_cap_yi')
            seal_txt = f"{seal}亿" if seal is not None else "N/A"
            fs = _fmt_hhmm(ztp.get('first_seal'))
            ot = ztp.get('open_times')
            ind = ztp.get('industry') or ''
            lines.append(f"\n**📈 打板池**\n{bc}板 · 涨停统计 {ztstat} · 封板资金 {seal_txt} · 首封 {fs} · 炸板 {ot}次 · {ind}")

        # 龙虎榜
        lhb = enrich.get('lhb') or {}
        if lhb.get('on_board'):
            net = lhb.get('net_yi')
            if net is None:
                net_txt = "N/A"
                emo = "⚪"
            else:
                emo = "🔴" if net > 0 else ("🟢" if net < 0 else "⚪")
                net_txt = f"{net}亿"
            reason = lhb.get('reason') or '—'
            explain = lhb.get('explain') or ''
            buy = lhb.get('buy_yi'); sell = lhb.get('sell_yi')
            extra = ""
            if buy is not None or sell is not None:
                extra = f" · 买{buy}/卖{sell}亿" if buy is not None and sell is not None else ""
            head = f"{reason}" + (f" · {explain}" if explain and explain != reason else "")
            lines.append(f"\n**🐉 龙虎榜**\n{head} · 净买额 {emo} {net_txt}{extra}")

    return title, lines, color


def _fmt_hhmm(v):
    """把 '092500' / '09:25:00' 这类时间格式化为 '09:25'。"""
    if not v:
        return "N/A"
    s = str(v).strip()
    s = s.replace(":", "")
    if len(s) >= 4:
        return s[:2] + ":" + s[2:4]
    return s or "N/A"


def send_stock_notification(webhook_url, stock_data):
    """发送单个股票的飞书通知"""
    if isinstance(stock_data, dict) and 'title' in stock_data and 'content' in stock_data:
        # 市场简报类型
        title = stock_data.get('title', '市场简报')
        content = stock_data.get('content', '')
        lines = content.split('\n') if isinstance(content, str) else [str(content)]
        return send_feishu_card(webhook_url, title, lines, FEISHU_COLORS['briefing'])

    if 'ticker' not in stock_data:
        return False

    title, lines, color = format_stock_card(stock_data)
    if not lines:
        return False

    return send_feishu_card(webhook_url, title, lines, color)


def send_notifications(webhook_url, stock_notifications):
    """批量发送飞书通知"""
    if not stock_notifications:
        logging.info("没有通知需要发送")
        return True

    if not webhook_url:
        logging.warning("飞书 Webhook URL 未配置，跳过")
        return False

    all_sent = True
    for item in stock_notifications:
        ok = send_stock_notification(webhook_url, item)
        if not ok:
            all_sent = False
    return all_sent


if __name__ == "__main__":
    # 测试
    config = load_config()
    if config:
        webhook = config.get('webhook_url', '')
        if webhook:
            send_feishu_card(webhook, "🧪 测试消息", ["这是一条来自 BreakoutAnalysis 的测试通知", "如果收到说明配置正确！"], 'purple')
