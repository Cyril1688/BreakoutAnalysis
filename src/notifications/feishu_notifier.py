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


def send_feishu_card(webhook_url, title, content_lines, color='blue'):
    """
    发送飞书交互式卡片消息
    
    Args:
        webhook_url: 飞书 Webhook URL
        title: 卡片标题
        content_lines: 内容行列表，每行为 markdown 字符串
        color: 卡片主题色 (blue/red/green/purple/grey)
    """
    if not webhook_url:
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

    try:
        resp = _get_requests().post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get('code') == 0:
            logging.info(f"飞书卡片发送成功: {title}")
            return True
        else:
            logging.error(f"飞书 API 返回错误: {result}")
            return False
    except _get_requests().exceptions.RequestException as e:
        logging.error(f"飞书 Webhook 请求失败: {e}")
        return False
    except Exception as e:
        logging.error(f"飞书发送异常: {e}")
        return False


def send_feishu_text(webhook_url, text):
    """发送纯文本消息（用于简单通知）"""
    if not webhook_url:
        return False
    payload = {
        "msg_type": "text",
        "content": {"text": text}
    }
    try:
        resp = _get_requests().post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"飞书文本消息发送失败: {e}")
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

    return title, lines, color


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


def send_briefing(webhook_url, title, content):
    """发送市场简报"""
    if not webhook_url:
        return False
    lines = content.split('\n') if isinstance(content, str) else [str(content)]
    return send_feishu_card(webhook_url, title, lines, FEISHU_COLORS['briefing'])


if __name__ == "__main__":
    # 测试
    config = load_config()
    if config:
        webhook = config.get('webhook_url', '')
        if webhook:
            send_feishu_card(webhook, "🧪 测试消息", ["这是一条来自 BreakoutAnalysis 的测试通知", "如果收到说明配置正确！"], 'purple')
