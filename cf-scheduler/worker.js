/**
 * Cloudflare Worker — BreakoutAnalysis 定时触发器
 * ============================================================
 * 复用 lof-monitor 项目的同一思路：用 Cloudflare 可靠的 Cron Trigger
 * 取代 GitHub Actions 不可靠的原生 schedule（高峰延迟/丢调度，
 * 美股时段几乎不被触发）。
 *
 * 每 30 分钟调用一次 GitHub 的 workflow_dispatch，
 * 由 Actions 内部的 is_any_market_open() 自行判断当前该跑
 * A股 / 美股 / 还是跳过（空档秒退，不浪费 CI）。
 *
 * 部署：
 *   cd cf-scheduler
 *   wrangler secret put GH_PAT   # 填入有 repo+workflow 权限的 GitHub PAT
 *   wrangler deploy
 */

const REPO = "Cyril1688/BreakoutAnalysis";
const WORKFLOW = "monitor.yml";

export default {
  // Cloudflare Cron Trigger 每 30 分钟调用（UTC，即北京时间整点半点）
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerWorkflow(env));
  },

  // 支持手动访问 GET / 触发一次，便于调试
  async fetch(request, env) {
    if (request.method !== "GET") {
      return new Response("Method Not Allowed", { status: 405 });
    }
    const r = await triggerWorkflow(env);
    return new Response(JSON.stringify(r, null, 2), {
      headers: { "Content-Type": "application/json" },
    });
  },
};

async function triggerWorkflow(env) {
  const token = env.GH_PAT;
  if (!token) {
    return { ok: false, error: "GH_PAT 未配置（wrangler secret put GH_PAT）" };
  }

  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cf-breakout-scheduler",
      },
      body: JSON.stringify({ ref: "main" }),
    });
    const text = await res.text();
    return { ok: res.ok, status: res.status, body: text };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}
