#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可行性门禁卡 —— v0.2.0 M0 产物

定位（源自第一性原理结论）：
  真实焦虑排序是「能不能成 > 会不会出事 > 花多少 > 玩什么」。
  护照 / 签证 / 疫苗 / 保险 任一红灯 → 整趟行程为 0，排程毫无意义。
  所以门禁卡不是「一个板块」，而是【放行条件】，必须前置到小册子顶部。

与既有 feasibility 的区别（避免重复造轮子）：
  - run_feasibility管的是【行程内部】的节奏/点位/末班船（境内为主）
  - gate_card 管的是【能不能成行】的准入四灯（出境为主，���内恒为绿）
  两者共用 feasibility_banner 的置顶渲染管道。

四灯定义：
  red    硬阻断。缺此项这趟走不成 → --gate strict 下直接中止渲染并输出拦停页
  yellow 有条件放行。需要在出发前落实（倒推时间窗/材料/保额）
  green  已满足
  grey   本次未提供信息，无法判定 → 绝不默认绿灯（默认绿是拿安全赌运气）
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any

RED, YELLOW, GREEN, GREY = "red", "yellow", "green", "grey"

_CN = {RED: "红", YELLOW: "黄", GREEN: "绿", GREY: "灰"}


def _esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ── 判定函数 ──────────────────────────────────────────────────────────────
def _check_passport(g: dict) -> dict:
    """护照：有效期是硬门槛（多数国家要求剩余有效期 > 6 个月）。"""
    months = g.get("passport_valid_months")
    if months is None:
        return {"light": GREY, "title": "护照有效期",
                "detail": "未提供护照有效期，无法判定是否满足多数国家的入境要求。",
                "action": "请先确认护照到期日，剩余有效期不足 6 个月应先换发。"}
    need = int(g.get("passport_required_months", 6))
    if int(months) >= need:
        return {"light": GREEN, "title": "护照有效期",
                "detail": f"剩余 {months} 个月，满足 ≥{need} 个月的常见入境要求。",
                "action": f"确认护照至少有 {max(2, need)} 页空白签证页。"}
    return {"light": RED, "title": "护照有效期",
            "detail": f"剩余仅 {months} 个月，不足多数目的地要求的 {need} 个月。",
            "action": "这是硬阻断项：先办理换发护照，否则可能在值机或入境时被拒。"}


def _check_visa(g: dict) -> dict:
    """签证：need 判定三态 —— required / none(免签) / unknown(待查)。"""
    need = g.get("visa_required")
    if need is None:
        return {"light": GREY, "title": "签证 / 免签",
                "detail": "未提供目的国签证政策，本次未核验，不作猜测。",
                "action": "请查中国领事服务网 cs.mfa.gov.cn 或目的国驻华使领馆官网，确认签证类型、材料与办理时长。"}
    if need == "none":
        return {"light": GREEN, "title": "签证 / 免签",
                "detail": "按内置基线为免签或落地签，仍需满足护照与入境材料要求。",
                "action": "确认停留期上限、入境卡与返程机票/住宿凭证等可能被查验证件。"}
    days = g.get("visa_lead_days")
    left = g.get("days_to_depart")
    if days and left is not None and int(left) < int(days):
        return {"light": RED, "title": "签证 / 免签",
                "detail": f"需要签证，办理约需 {days} 天，而距出发仅 {left} 天，时间已不够。",
                "action": "加急办理并确认是否提供加急通道；若无法出签，这趟行程不成立。"}
    if days and left is not None and int(left) - int(days) <= 3:
        return {"light": YELLOW, "title": "签证 / 免签",
                "detail": f"需签证，约需 {days} 天，距出发 {left} 天，仅剩 {int(left)-int(days)} 天余量。",
                "action": "材料一次性备齐递交，务必留出补件时间，否则极易赶不上。"}
    return {"light": YELLOW if need != "unknown" else GREY, "title": "签证 / 免签",
            "detail": f"按内置基线需要签证{'（办理约需 ' + str(days) + ' 天）' if days else ''}。",
            "action": "递交前复核材料清单与受理时长；签证政策属易变信息，请以官网当日为准。"}


def _check_vaccine(g: dict) -> dict:
    """疫苗 / 健康证明：未提供不等于不需要 —— 问清楚，别赌。"""
    req = g.get("vaccine_required")
    if req is None:
        return {"light": GREY, "title": "疫苗 / 健康证明",
                "detail": "未提供目的地健康准入要求，无法判定。",
                "action": "确认目的地是否要求疫苗接种证明、黄热病证书或其他健康申报。"}
    if req == "none":
        return {"light": GREEN, "title": "疫苗 / 健康证明",
                "detail": "按内置基线无特殊疫苗或健康证明要求。",
                "action": "如携带管制药品，备原包装与处方，见「合规与文化」板块。"}
    return {"light": YELLOW, "title": "疫苗 / 健康证明",
            "detail": "目的地可能要求疫苗接种证明或健康申报。",
            "action": "按目的地官方卫生部门要求提前接种，注意黄热病证书通常需提前 10 天生效。"}


def _check_insurance(g: dict) -> dict:
    """保险：申根等要求医疗保额，部分签证会核查。"""
    amount = g.get("insurance_amount")
    required = g.get("insurance_required")
    if required is False:
        return {"light": GREEN, "title": "旅行保险",
                "detail": "目的地无强制保险要求。",
                "action": "仍强烈建议购买含医疗与紧急救援的旅行保险。"}
    if amount is None:
        return {"light": YELLOW, "title": "旅行保险",
                "detail": "目的地可能要求含医疗与紧急救援的旅行保险，部分签证会核查保单。",
                "action": "购买含医疗与紧急救援的旅行保险，保存保单号与 24 小时救援电话。"}
    floor = g.get("insurance_min_amount", 0)
    if int(amount) < int(floor):
        return {"light": RED, "title": "旅行保险",
                "detail": f"当前保额 {amount}，低于目的地要求的最低 {floor}。",
                "action": "补足保额后再提交签证，否则可能被拒签。"}
    return {"light": GREEN, "title": "旅行保险",
            "detail": f"已配置保额 {amount}，满足目的地要求。",
            "action": "确认保险覆盖高原/潜水/骑马等实际活动项，并记录救援电话。"}


CHECKERS = {
    "passport": _check_passport,
    "visa": _check_visa,
    "vaccine": _check_vaccine,
    "insurance": _check_insurance,
}


# ── 主入口 ────────────────────────────────────────────────────────────────
def gate_card(gate: dict | None) -> dict:
    """返回 {cards, red, yellow, green, grey, blocked, verdict}。

    gate 由调用方从 plan 提供，形如：
        {"passport_valid_months": 11, "visa_required": "required",
         "visa_lead_days": 7, "days_to_depart": 5, ...}
    国内行程传 None → 四灯全绿（境内无准入门槛），不渲染门禁卡。
    """
    if not gate:
        return {"cards": [], "red": 0, "yellow": 0, "green": 0, "grey": 0,
                "blocked": False, "verdict": "domestic"}
    cards = []
    for key, fn in CHECKERS.items():
        item = gate.get(key)
        if isinstance(item, dict):
            merged = dict(item)
            merged.setdefault("_explicit", True)
            r = fn(merged)
        else:
            r = fn(gate)
        cards.append(r)
    counts = {l: sum(1 for c in cards if c["light"] == l) for l in (RED, YELLOW, GREEN, GREY)}
    blocked = counts[RED] > 0
    verdict = "blocked" if blocked else ("caution" if (counts[YELLOW] or counts[GREY]) else "clear")
    return {"cards": cards, "red": counts[RED], "yellow": counts[YELLOW],
            "green": counts[GREEN], "grey": counts[GREY],
            "blocked": blocked, "verdict": verdict}


# ── 渲染 ──────────────────────────────────────────────────────────────────
_STYLE = {
    RED: ("#FCEBEB", "#A32D2D", "#791F1F", "⛔"),
    YELLOW: ("#FAEEDA", "#BA7517", "#633806", "⚠"),
    GREEN: ("#EAF3DE", "#639922", "#27500A", "✅"),
    GREY: ("#F1EFE8", "#888780", "#444441", "◐"),
}


def gate_html(g: dict) -> str:
    """门禁卡 HTML：四灯横排 + 逐项明细。置于小册子顶部。"""
    if not g or not g.get("cards"):
        return ""
    if g.get("verdict") == "domestic":
        return ""
    q = []
    q.append(f'<div class="sec-open" id="gate"><div class="sec-no">◉</div><div>'
             f'<h2>可行性门禁卡</h2>'
             f'<p class="sec-sub">先看能不能成行，再谈怎么玩 · 四项准入与保障自检</p></div></div>')

    lamps = ""
    for c in g["cards"]:
        bg, stroke, fg, ico = _STYLE[c["light"]]
        lamps += (f'<div style="flex:1;min-width:150px;background:{bg};border:1px solid {stroke};'
                  f'border-radius:12px;padding:12px 14px">'
                  f'<div style="font-size:12px;color:{fg};opacity:.85">{ico} {_CN[c["light"]]}灯</div>'
                  f'<div style="font-size:14px;font-weight:500;color:{fg};margin:3px 0 5px">{_esc(c["title"])}</div>'
                  f'<div style="font-size:12px;line-height:1.55;color:{fg}">{_esc(c["detail"])}</div></div>')

    rows = ""
    for c in g["cards"]:
        bg, stroke, fg, ico = _STYLE[c["light"]]
        rows += (f'<li style="margin:0 0 9px"><b>{_esc(c["title"])}</b> '
                 f'<span class="feat-badge" style="background:{stroke}22;color:{fg};border:1px solid {stroke}">'
                 f'{ico} {_CN[c["light"]]}灯</span>'
                 f'<div style="font-size:13px;line-height:1.6;color:var(--sub);margin-top:3px">'
                 f'{_esc(c["detail"])}</div>'
                 f'<div style="font-size:13px;line-height:1.6;margin-top:3px">'
                 f'<b>要做什么：</b>{_esc(c["action"])}</div></li>')

    verdict_html = {
        "blocked": ('<div class="card" style="border:1px solid #A32D2D;background:#FCEBEB">'
                    '<h3>⛔ 当前不满足成行条件</h3>'
                    '<p style="margin:0;font-size:13px;line-height:1.65;color:#501313">'
                    '存在红灯硬阻断项——它与行程好不好玩无关，但没解决这趟就走不成。'
                    '请先处理下方红灯项，再看行程安排；此时照原计划出行很可能白跑一趟。</p></div>'),
        "caution": ('<div class="card" style="border:1px solid #BA7517;background:#FAEEDA">'
                    '<h3>⚠ 有条件放行：存在黄灯或待确认项</h3>'
                    '<p style="margin:0;font-size:13px;line-height:1.65;color:#412402">'
                    '没有硬阻断，但有事项需要在出发前落实或确认。'
                    '把黄灯项逐条清掉，这趟就稳了；灰灯项请自行查证，不要默认它没问题。</p></div>'),
        "clear": ('<div class="card" style="border:1px solid #639922;background:#EAF3DE">'
                  '<h3>✅ 准入条件齐备</h3>'
                  '<p style="margin:0;font-size:13px;line-height:1.65;color:#173404">'
                  '四项准入与保障自检均通过，可以进入行程安排。'
                  '签证与汇率等易变信息请在出行前 1–3 天再核验一次。</p></div>'),
    }[g["verdict"]]

    return ("\n".join(q) +
            f'<div class="card"><h3>准入四灯<span class="feat-badge">'
            f'{"硬阻断" if g["blocked"] else ("待落实" if g["verdict"] == "caution" else "通过")}</span></h3>'
            f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:6px">{lamps}</div></div>'
            f'<div class="card"><h3>逐项明细与行动项</h3><ul class="kv">{rows}</ul></div>'
            + verdict_html)


def blocked_page(g: dict, dest: str) -> str:
    """红灯拦停页：--gate strict 下红灯时输出，不渲染行程正文。

    这是「红灯先拦再谈行程」的强制执行点——不是提示，是不放行。
    """
    items = ""
    for c in g["cards"]:
        if c["light"] != RED:
            continue
        items += (f'<li style="margin:0 0 10px"><b>{_esc(c["title"])}</b>'
                  f'<div style="font-size:13px;line-height:1.6;color:var(--sub);margin-top:3px">{_esc(c["detail"])}</div>'
                  f'<div style="font-size:13px;line-height:1.6;margin-top:4px"><b>要做什么：</b>{_esc(c["action"])}</div></li>')
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>准入未通过 · {_esc(dest)}</title>
<style>
:root {{ --accent:#0071E3; --bg:#F5F5F7; --card:#FFF; --sub:#6E6E73; }}
*{{box-sizing:border-box}}
body {{ margin:0; background:var(--bg); color:#1D1D1F;
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; -webkit-font-smoothing:antialiased; }}
.wrap {{ max-width:860px; margin:0 auto; padding:44px 18px 60px; }}
.card {{ background:var(--card); border-radius:18px; padding:22px 20px; margin:0 0 14px;
  border:1px solid #E5E5EA; }}
h1 {{ font-size:26px; font-weight:600; letter-spacing:-.02em; margin:0 0 10px; }}
h3 {{ font-size:16px; font-weight:500; margin:0 0 12px; }}
ul {{ margin:0; padding-left:20px; }}
p {{ margin:0 0 10px; }}
.hint {{ font-size:12.5px; color:var(--sub); margin-top:26px; padding-top:14px; border-top:1px solid #E5E5EA; }}
</style>
</head>
<body><div class="wrap">
<div class="card" style="border:1px solid #A32D2D;background:#FCEBEB">
<h1>⛔ 准入未通过，行程暂不成立</h1>
<p style="font-size:14px;line-height:1.7;color:#501313;margin:0">
本次规划「{_esc(dest)}」，但存在 <b>{g['red']}</b> 项硬阻断条件。
它们与好不好玩无关，但在解决之前，出行无法成行——因此这里不放行行程正文，
只列出必须先解决的事。把它们清掉后重新生成即可。
</p>
</div>
<div class="card"><h3>必须先解决（{g['red']} 项）</h3><ul>{items}</ul></div>
<div class="card"><h3>核验渠道</h3><ul>
<li>签证 / 免签 / 材料：<b>中国领事服务网 cs.mfa.gov.cn</b>，或目的国驻华使领馆官网</li>
<li>安全提醒：<b>外交部全球安全提醒 cs.mfa.gov.cn</b></li>
<li>领事保护：<b>12308</b>（境外拨 +86-10-12308）</li>
<li>保险保额：以签证材料清单与保险公司条款为准</li>
</ul></div>
<p class="hint">提示：本页由 worldstip-travel-planner 可行性门禁卡生成。
门禁卡只判断「能不能成」，不判断「好不好玩」——请先让行程成行，再谈如何取舍。</p>
</div></body></html>"""


if __name__ == "__main__":
    import sys
    print("── 案例1 红灯（时间不够+保额不足）──")
    g = gate_card({"passport_valid_months": 3, "visa_required": "required",
                   "visa_lead_days": 7, "days_to_depart": 2,
                   "vaccine_required": "none", "insurance_amount": 20000,
                   "insurance_min_amount": 30000})
    print(json.dumps({k: v for k, v in g.items() if k != "cards"}, ensure_ascii=False))
    for c in g["cards"]:
        print(f"  {_CN[c['light']]}灯 {c['title']}: {c['detail']}")
    print()
    print("── 案例2 全绿 ──")
    g2 = gate_card({"passport_valid_months": 24, "visa_required": "required",
                    "visa_lead_days": 7, "days_to_depart": 30,
                    "vaccine_required": "none", "insurance_required": False})
    print(json.dumps({k: v for k, v in g2.items() if k != "cards"}, ensure_ascii=False))
    print()
    print("── 案例3 未提供（国内，应跳过）──")
    print(gate_card(None)["verdict"])
    print(len(gate_html(g)) > 0, len(gate_html(g2)) > 0, len(gate_html(gate_card(None))) == 0)
    sys.exit(0)
