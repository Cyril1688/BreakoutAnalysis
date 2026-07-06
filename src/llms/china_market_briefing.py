"""
China A-Share Market Briefing Client.
Fetches A-share market index data (上证指数, 深证成指, 创业板指, 科创50) and generates AI briefing.
"""

import logging
import os
import sys
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - CHINA_BRIEFING - %(levelname)s - %(message)s')


class ChinaMarketBriefingClient:
    """
    Generates market briefing for A-share market using akshare index data.
    """

    def __init__(self):
        self.config = {}
        self._load_config()

    def _load_config(self):
        """Load config for AI model if available."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        config_path = os.path.join(project_root, 'config', 'config.json')
        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        except Exception as e:
            logging.warning(f"Could not load config for China briefing: {e}")

    def get_china_market_data(self):
        """
        Fetch A-share major index data using akshare.
        Returns a dict with index name, current value, change, etc.
        """
        try:
            import akshare as ak
            
            # Get major A-share indices
            indices = {
                '上证指数': '000001',
                '深证成指': '399001', 
                '创业板指': '399006',
                '科创50': '000688',
            }
            
            index_data = {}
            
            # Fetch all index data
            for name, code in indices.items():
                try:
                    # Try to get index real-time data
                    df = ak.stock_zh_index_spot_em()
                    if df is not None and not df.empty:
                        index_row = df[df['代码'] == code]
                        if not index_row.empty:
                            row = index_row.iloc[0]
                            index_data[name] = {
                                'code': code,
                                'current': float(row.get('最新价', 0)),
                                'change_percent': float(row.get('涨跌幅', 0)),
                                'change_amount': float(row.get('涨跌额', 0)),
                                'volume': float(row.get('成交量', 0)),
                                'turnover': float(row.get('成交额', 0)),
                            }
                except Exception as e:
                    logging.debug(f"Could not fetch {name} ({code}): {e}")
            
            return index_data
            
        except ImportError:
            logging.warning("akshare not available for China market data.")
            return {}
        except Exception as e:
            logging.error(f"Error fetching China market data: {e}")
            return {}

    def get_china_sector_movers(self, top_n=5):
        """
        Get top/bottom performing sectors in A-share market.
        """
        try:
            import akshare as ak
            
            # Get sector/industry performance
            sector_df = ak.stock_board_industry_name_em()
            
            if sector_df is not None and not sector_df.empty:
                # Sort by change percent
                sector_df = sector_df.sort_values('涨跌幅', ascending=False)
                
                top_sectors = []
                bottom_sectors = []
                
                for _, row in sector_df.head(top_n).iterrows():
                    top_sectors.append({
                        'name': row.get('板块名称', ''),
                        'change_percent': float(row.get('涨跌幅', 0)),
                    })
                
                for _, row in sector_df.tail(top_n).iterrows():
                    bottom_sectors.append({
                        'name': row.get('板块名称', ''),
                        'change_percent': float(row.get('涨跌幅', 0)),
                    })
                
                return {'top': top_sectors, 'bottom': bottom_sectors}
            
        except ImportError:
            pass
        except Exception as e:
            logging.error(f"Error fetching China sector data: {e}")
        
        return {'top': [], 'bottom': []}

    def generate_china_briefing(self):
        """
        Generate a comprehensive A-share market briefing text.
        """
        index_data = self.get_china_market_data()
        sector_data = self.get_china_sector_movers()
        
        lines = []
        lines.append(f"**A股市场简报 — {datetime.now().strftime('%Y-%m-%d %H:%M')}**\n")
        
        # Index data
        if index_data:
            lines.append("**📊 主要指数**")
            for name, data in index_data.items():
                change = data.get('change_percent', 0)
                emoji = "🔴" if change > 0 else ("🟢" if change < 0 else "⚪")
                lines.append(
                    f"{emoji} **{name}**: {data.get('current', 'N/A'):.2f} "
                    f"({change:+.2f}%) 成交额: {data.get('turnover', 0)/1e8:.0f}亿"
                )
        
        # Sector movers
        if sector_data.get('top'):
            lines.append("\n**🏆 领涨板块**")
            for s in sector_data['top']:
                lines.append(f"  🔺 {s['name']}: {s['change_percent']:+.2f}%")
        
        if sector_data.get('bottom'):
            lines.append("\n**📉 领跌板块**")
            for s in sector_data['bottom']:
                lines.append(f"  🔻 {s['name']}: {s['change_percent']:+.2f}%")
        
        return "\n".join(lines)


if __name__ == "__main__":
    briefing = ChinaMarketBriefingClient()
    text = briefing.generate_china_briefing()
    print(text)
