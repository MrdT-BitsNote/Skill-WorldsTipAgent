#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 suggest_trip.py 的短途灵感渲染成华丽单文件 HTML(可一键导出 PDF)。

用法:
  python render_suggestion.py --plan suggest.json --out idea.html
  python render_suggestion.py --plan suggest.json --out idea.html --title "周末去哪"

设计: 季节主题渐变 + 玻璃卡片 + 动效; 右下角悬浮「保存为 PDF」按钮,
点击即调起浏览器打印(已内置打印样式, 排版清晰可分享保存)。
"""
import argparse
import html
import json
from pathlib import Path

# 季节 → 主题色(与 render_report 同调性)
SEASON_THEME = {
    "春": ("#1D9E75", "#9BD9B8"),
    "夏": ("#00838F", "#4DD0E1"),
    "秋": ("#BA7517", "#F2C879"),
    "冬": ("#378ADD", "#9CC4F0"),
}
STYLE_LABEL = {
    "leisure": "休闲", "commando": "特种兵", "resort": "度假", "honeymoon": "蜜月",
    "roadtrip": "自驾", "cycling": "骑行", "hiking": "徒步", "moto": "摩旅",
    "family": "亲子", "couple": "情侣", "friends": "朋友", "camping": "露营",
    "rv": "房车", "budget": "穷游", "photo": "摄影", "study": "研学",
    "silver": "银发", "ski": "滑雪", "island": "海岛", "ancient": "古镇", "rail": "高铁周边",
}

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--font:system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
body{font-family:var(--font);background:#f6f3ee;color:#2b2333;line-height:1.6;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:0 auto;padding:0 18px 60px}
.hero{background:linear-gradient(135deg,var(--a),var(--b));color:#fff;padding:42px 18px 34px;
  position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;right:-80px;top:-80px;width:280px;height:280px;
  background:radial-gradient(circle,rgba(255,255,255,.28),transparent 70%);border-radius:50%}
.hero-in{max-width:980px;margin:0 auto;position:relative;z-index:1}
.kicker{font-size:12px;letter-spacing:.32em;text-transform:uppercase;opacity:.85}
.hero h1{font-size:34px;font-weight:700;margin:10px 0 6px;line-height:1.2}
.sub{font-size:15px;opacity:.95;margin-top:6px}
.pill{display:inline-flex;align-items:center;gap:7px;background:rgba(255,255,255,.22);
  border:1px solid rgba(255,255,255,.35);padding:6px 14px;border-radius:999px;
  font-size:13px;margin-top:14px;backdrop-filter:blur(4px)}
.pill b{font-weight:600}

.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));margin-top:22px}
.card{background:rgba(255,255,255,.9);backdrop-filter:blur(6px);border:1px solid #efe6da;
  border-radius:16px;padding:18px 18px 16px;position:relative;overflow:hidden;
  box-shadow:0 6px 22px rgba(120,90,40,.08);transition:transform .18s,box-shadow .18s}
.card:hover{transform:translateY(-4px);box-shadow:0 12px 30px rgba(120,90,40,.16)}
.card::before{content:"";position:absolute;left:0;top:0;width:100%;height:5px;
  background:linear-gradient(90deg,var(--a),var(--b))}
.num{position:absolute;right:14px;top:12px;font-size:30px;font-weight:800;color:var(--a);opacity:.16;
  font-family:ui-monospace,Menlo,Consolas,monospace}
.ctitle{font-size:19px;font-weight:700;margin-bottom:9px;padding-right:36px}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:11px}
.tag{font-size:11.5px;background:#f3ece1;color:#6b5d4a;padding:3px 9px;border-radius:999px}
.tag.s{background:var(--a);color:#fff}
.why{font-size:13px;color:#5a5266;background:#fbf7f1;border-left:3px solid var(--b);
  border-radius:7px;padding:9px 11px;margin-bottom:11px;line-height:1.55}
.hl{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:11.5px;background:#fff;border:1px solid #e8ddcd;color:#5a5266;
  padding:3px 9px;border-radius:7px}
.foot{text-align:center;color:#9a8f80;font-size:12px;margin-top:30px;
  padding-top:18px;border-top:1px solid #e8ddcd}
.pdf{position:fixed;right:18px;bottom:18px;z-index:50;background:linear-gradient(135deg,var(--a),var(--b));
  color:#fff;border:none;border-radius:999px;padding:13px 20px;font-size:14px;font-weight:600;
  cursor:pointer;box-shadow:0 8px 24px rgba(120,90,40,.32);display:flex;align-items:center;gap:7px}
.pdf:hover{filter:brightness(1.07)}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.card{animation:rise .5s both}
.card:nth-child(2){animation-delay:.06s}.card:nth-child(3){animation-delay:.12s}
.card:nth-child(4){animation-delay:.18s}.card:nth-child(5){animation-delay:.24s}
@media print{
  body{background:#fff}
  .hero{print-color-adjust:exact;-webkit-print-color-adjust:exact;padding:24px 14px}
  .pdf{display:none}
  .card{box-shadow:none;break-inside:avoid;animation:none}
  .wrap{padding:0 8px 30px}
}
@media (max-width:640px){.hero h1{font-size:26px}.grid{grid-template-columns:1fr}}
"""

JS = """<script>
function savePDF(){window.print();}
// 进入视口渐显
var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting)e.target.style.animationPlayState='running';});},{threshold:.1});
document.querySelectorAll('.card').forEach(function(c){c.style.animationPlayState='paused';io.observe(c);});
</script>"""


def render(data: dict, title: str = "") -> str:
    season = data.get("season", "秋")
    a, b = SEASON_THEME.get(season, SEASON_THEME["秋"])
    occ = data.get("occasion", {})
    picks = data.get("picks", [])
    h1 = title or "周末去哪 · 短途灵感"
    occ_label = occ.get("label", "")
    wk = occ.get("weekend", "")

    cards = []
    for i, p in enumerate(picks, 1):
        sl = STYLE_LABEL.get(p.get("style", ""), p.get("style", ""))
        tags = (f'<span class="tag s">{esc(p.get("region",""))}</span>'
                f'<span class="tag">{p.get("days")} 天</span>'
                f'<span class="tag">{esc(sl)}</span>')
        chips = "".join(f'<span class="chip">{esc(h)}</span>' for h in p.get("highlights", []))
        cards.append(f"""<div class="card">
<div class="num">{i}</div>
<div class="ctitle">{esc(p.get('title',''))}</div>
<div class="meta">{tags}</div>
<div class="why">💡 {esc(p.get('why',''))}</div>
<div class="hl">{chips}</div>
</div>""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(h1)} · 短途灵感</title>
<style>{CSS}</style></head>
<body style="--a:{a};--b:{b}">
<div class="hero"><div class="hero-in">
<div class="kicker">短途灵感</div>
<h1>{esc(h1)}</h1>
<div class="sub">{esc(season)}季推荐 · 结合临近周末与节假日</div>
<div class="pill">🗓️ <b>{esc(occ_label)}</b>{f' · {esc(wk)}' if wk else ''}</div>
</div></div>
<div class="wrap">
<div class="grid">{''.join(cards)}</div>
<div class="foot">{esc(data.get('disclaimer',''))}<br>
由 AI 旅行规划技能生成 · 分类：旅行 · 范围：中国大陆国内 · 支持多语言</div>
</div>
<button class="pdf" onclick="savePDF()">📄 保存为 PDF</button>
{JS}
</body></html>"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染短途灵感 HTML")
    ap.add_argument("--plan", required=True, help="suggest_trip.py --json 的输出")
    ap.add_argument("--out", required=True, help="输出 HTML")
    ap.add_argument("--title", help="自定义大标题")
    args = ap.parse_args()
    data = json.load(open(args.plan, encoding="utf-8"))
    html_out = render(data, args.title or "")
    Path(args.out).write_text(html_out, encoding="utf-8")
    kb = Path(args.out).stat().st_size / 1024
    print(f"已生成: {args.out} ({kb:.1f} KB)")
    print("保存为 PDF: 点右下角「保存为 PDF」按钮 → 浏览器打印 → 另存为 PDF")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
