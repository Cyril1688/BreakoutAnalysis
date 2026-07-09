"""
跨运行去重模块（BreakoutAnalysis）
================================

解决 Cloudflare Worker 每 20 分钟触发一次 GitHub Actions 时，同一只股票被
反复推送的问题。

根因：每次 Actions 运行都是干净的新容器，工作区被重新 checkout，上一轮写入的
`analysis.json` / `notify.json` 全部丢失，导致"当天去重"逻辑失效。

本模块把"今天通知过哪些股票 / 通知了几次 / 强度如何"持久化到仓库内的
`state/dedup_state.json`，每次运行：
  - 开头 git pull 拉取最新状态（跨运行持久化的关键）
  - 用冷却期 + 计数 + 强度升级逻辑决定每只股推不推、以什么标签推
  - 发送后 git push 写回（若 GITHUB_TOKEN 无写权限则自动降级，不影响主流程）

因为 monitor.yml 只监听 `workflow_dispatch`（不是 push），推送状态文件不会引发
循环触发，安全。
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone

logger = logging.getLogger("DEDUP")

# 状态文件路径（相对仓库根目录；Actions 中 cwd 即仓库根）
STATE_PATH = "state/dedup_state.json"

# 默认参数（可被 config.json 的 notifiers.dedup 覆盖）
DEFAULT_COOLDOWN_MIN = 40       # 同一只股票两次通知的最小间隔（分钟）
DEFAULT_UPGRADE_DELTA = 2.0     # 涨跌幅相对上次变化超过此值视为"强度升级"
DEFAULT_MAX_PER_DAY = 6         # 单只股票单日最多通知次数（安全阀，防极端刷屏）


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _today_key():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _git(*args, timeout=60):
    """执行 git 命令，返回 CompletedProcess；任何异常都吞掉（不阻塞主流程）。"""
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as e:
        logger.debug(f"git {' '.join(args)} 执行异常: {e}")
        return None


def load_state(path=STATE_PATH):
    """加载去重状态；优先 git pull 最新，失败则使用本地文件。"""
    # 拉取远端最新状态（跨运行持久化的关键）
    _git("pull", "--ff-only", "origin", "main")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.warning("读取去重状态失败，重新开始。")
    return {}


def save_state(state, path=STATE_PATH):
    """写回去重状态并 git push（无写权限则静默降级，不阻塞主流程）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"写入去重状态失败: {e}")
        return

    _git("add", path)
    _git("commit", "-m", "chore: update dedup state [skip ci]")
    # push 失败（如无写权限）不阻塞主流程
    r = _git("push", "origin", "main")
    if r is None or r.returncode != 0:
        logger.warning(
            "去重状态 push 失败（可能 GITHUB_TOKEN 无写权限）。"
            "去重在本轮仍生效，但不跨运行持久化——请到仓库 "
            "Settings → Actions → Workflow permissions 开启 Read and write。"
        )


def classify(state, ticker, change_pct, market='us',
             cooldown_min=DEFAULT_COOLDOWN_MIN,
             upgrade_delta=DEFAULT_UPGRADE_DELTA,
             max_per_day=DEFAULT_MAX_PER_DAY):
    """
    判断一只股票本次是否应通知、以及以什么标签通知。

    返回 dict:
      {
        "action": "new" | "repeat" | "upgrade" | "suppress",
        "count": int,            # 今日累计通知次数（含本次）
        "first_change": float,   # 今日首次通知时的涨跌幅
        "last_change": float,    # 本次（或上次）通知时的涨跌幅
      }
    action == "suppress" 表示冷却期内且强度未升级 → 不通知。
    """
    today = _today_key()
    now = datetime.now(timezone.utc)
    rec = state.get(ticker)

    # 跨天 / 不存在 → 全新
    if not rec or rec.get("date") != today:
        new_rec = {
            "date": today,
            "count": 1,
            "first_change": change_pct,
            "last_change": change_pct,
            "last_ts": _now_iso(),
            "market": market,
        }
        state[ticker] = new_rec
        return {
            "action": "new",
            "count": 1,
            "first_change": change_pct,
            "last_change": change_pct,
        }

    # 已存在且同日
    last_ts = rec.get("last_ts")
    in_cooldown = False
    if last_ts:
        try:
            lt = datetime.fromisoformat(last_ts)
            elapsed = (now - lt).total_seconds() / 60.0
            in_cooldown = elapsed < cooldown_min
        except Exception:
            in_cooldown = False

    last_change = rec.get("last_change", change_pct)
    delta = abs(change_pct - last_change)
    upgraded = delta >= upgrade_delta

    if in_cooldown and not upgraded:
        # 冷却期内且无强度升级 → 抑制（不通知），不更新 last_ts
        return {
            "action": "suppress",
            "count": rec.get("count", 1),
            "first_change": rec.get("first_change", change_pct),
            "last_change": last_change,
        }

    # 安全阀：单日次数超限则抑制
    new_count = rec.get("count", 0) + 1
    if new_count > max_per_day:
        return {
            "action": "suppress",
            "count": new_count,
            "first_change": rec.get("first_change", change_pct),
            "last_change": last_change,
        }

    # 需要通知：repeat（普通重复）或 upgrade（强度升级）
    rec["count"] = new_count
    rec["last_change"] = change_pct
    rec["last_ts"] = _now_iso()
    rec["market"] = market
    action = "upgrade" if upgraded else "repeat"
    return {
        "action": action,
        "count": new_count,
        "first_change": rec.get("first_change", change_pct),
        "last_change": change_pct,
    }
