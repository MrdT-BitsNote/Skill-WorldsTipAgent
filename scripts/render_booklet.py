#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旅行指南小册子 · 苹果风 HTML 渲染器。

用法:
  python render_booklet.py --plan plan.json --research research.json \
    --weather weather.json --poi poi.json --context context.json \
    --transit transit.json --out 旅行小册子.html

视觉规范 (Apple-style):
  - 浅色 #F5F5F7 背景 + 白色大圆角卡片 (18px) + 柔和阴影
  - 系统字体栈: -apple-system / SF Pro / PingFang SC
  - 毛玻璃 sticky 导航 (backdrop-filter), 板块自动编号
  - 内容详实、布局紧凑 (13.5px 正文), 现代化结构
  - 一键「保存为 PDF」按钮 + @media print 打印优化
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

# UGC 抓取渲染模块（ugc_badge）已随平台合规整改移除（见 SKILL.md v0.1.17 ⑭）。
# _sec_ugc / _sec_pitfall 保留 None 守卫恒返回空串，公开检索结论改由紧凑版渲染器以文字呈现。
_render_ugc = None      # type: ignore[assignment]
_to_sorted = None       # type: ignore[assignment]
_render_pitfalls = None  # type: ignore[assignment]

REF = Path(__file__).resolve().parent.parent / "references"
SEASON_DATA = REF / "seasons_climate.json"
SAFETY_DATA = REF / "safety_playbook.json"
PACKING_DATA = REF / "packing_checklist.json"
EXTREME_DATA = REF / "extreme_sports.json"
PHOTO_DATA = REF / "photography_guide.json"
CONCERT_DATA = REF / "concert_playbook.json"
WX_CONTINGENCY_DATA = REF / "weather_contingency.json"
CARBON_DATA = REF / "carbon_factors.json"
ALTITUDE_DATA = REF / "altitude_playbook.json"
LOST_DATA = REF / "lost_items_playbook.json"

# 高反应急：就近就医参考枢纽（真实经纬度，用于最近邻映射）
MED_HUBS = {
    "成都": (30.57, 104.07), "昆明": (25.04, 102.71), "西安": (34.27, 108.95),
    "兰州": (36.06, 103.83), "乌鲁木齐": (43.83, 87.62), "拉萨": (29.65, 91.13),
    "西宁": (36.62, 101.78), "重庆": (29.56, 106.55), "贵阳": (26.65, 106.63),
}
# 高原/高海拔目的地关键词（命中即触发高反应急预案）
HIGH_KEYWORDS = ("拉萨", "丽江", "稻城", "香格里拉", "西宁", "昆明", "大理", "九寨",
                 "林芝", "海西", "甘孜", "阿坝", "昌都", "玉树", "迪庆", "峨眉", "天山", "那曲")

ACCENT = "#0071E3"
OK, WARN, TIP, CAUTION, BAD = "#34C759", "#FF3B30", "#34C759", "#FF9500", "#FF3B30"

# 每个板块一套 Apple 系统强调色：白底深字 + 该板块专属色调，分区清晰又不花哨
SECTION_ACCENT = {
    "overview": "#0071E3",   # 蓝
    "season":   "#FF9500",   # 橙
    "route":    "#AF52DE",   # 紫
    "transit":  "#30B0C7",   # 青
    "research": "#FF2D55",   # 粉
    "weather":  "#34C759",   # 绿
    "poi":      "#5856D6",   # 靛
    "context":  "#5AC8FA",   # 浅蓝
    "photo":    "#FFCC00",   # 黄
    "concert":  "#FF375F",   # 玫红
    "stay":     "#FF9F0A",   # 琥珀
    "budget":   "#30D158",   # 翠绿
    "extreme":  "#FF453A",   # 红
    "packing":  "#64D2FF",   # 天蓝
    "safety":   "#FF3B30",   # 警示红
    "prefs":    "#BF5AF2",   # 紫粉
    "cold":     "#5E5CE6",   # 蓝紫
    "audience": "#FF6482",   # 浅粉
    "feasibility": "#30B0C7",  # 青（体检）
    "profile": "#BF5AF2",   # 紫粉（偏好档案）
    "wxb": "#30B0C7",      # 青（天气突变预案）
    "carbon": "#30D158",   # 翠绿（碳足迹）
    "pitfall": "#FF3B30",  # 警示红（避雷）
    "altitude": "#FF9500", # 琥珀（高反应急）
    "lost": "#AF52DE",    # 紫粉（证件财物应急）
}

# 预算分项环形图配色（与 Apple 强调色体系一致）
BUDGET_COLORS = {
    "交通": "#0071E3", "住宿": "#FF9F0A", "餐饮": "#34C759",
    "门票": "#FF2D55", "其他": "#5AC8FA", "购物": "#AF52DE",
}

import math
import os
import sys

# ───────────────────────── 风格系统（v0.0.9）：按行程类型自动选风 + --style 手动覆盖
# 每个风格只列出与苹果默认不同的令牌；apple 为基准（APPLE_VARS），其余合并覆盖。
APPLE_VARS = {
    "--bg": "#F5F5F7", "--card": "#FFFFFF", "--ink": "#1D1D1F", "--sub": "#6E6E73",
    "--line": "rgba(0,0,0,.08)",
    "--accent": "#0071E3", "--accent2": "#5AC8FA", "--accent-soft": "rgba(0,113,227,.10)",
    "--ok": "#34C759", "--warn": "#FF3B30", "--caution": "#FF9500", "--tip": "#34C759",
    "--radius": "18px",
    "--shadow-card": "0 1px 2px rgba(0,0,0,.03),0 4px 14px rgba(0,0,0,.05)",
    "--shadow-soft": "0 8px 22px rgba(0,0,0,.07)",
    "--font": '-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","PingFang SC","Helvetica Neue","Segoe UI",sans-serif',
    "--node-stroke": "#0071E3", "--route-line": "#C7C7CC", "--stamina": "#FF9500",
    "--hero-bg": "transparent",
    "--cover-grad": "linear-gradient(135deg,#FFE3EC,#E6F0FF 55%,#E9FBF0)",
    "--blank-grad": "linear-gradient(135deg,#EEF3FF,#F2ECFF)",
    "--toc-bg": "rgba(255,255,255,.72)", "--toc-border": "rgba(0,0,0,.08)",
}

STYLES = {
    "apple": {"label": "苹果极简", "per_section_accent": False, "vars": {}, "deco": ""},
    "mecha": {
        "label": "机甲工业", "per_section_accent": False,
        "vars": {
            "--bg": "#0E1116", "--card": "#171C24", "--ink": "#E6EDF3", "--sub": "#8B98A5",
            "--line": "rgba(255,255,255,.10)",
            "--accent": "#00E5FF", "--accent2": "#FFB000", "--accent-soft": "rgba(0,229,255,.14)",
            "--ok": "#3DDC84", "--warn": "#FF4D4D", "--caution": "#FFB000", "--tip": "#3DDC84",
            "--radius": "6px",
            "--shadow-card": "0 0 0 1px rgba(0,229,255,.18),0 10px 26px rgba(0,0,0,.55)",
            "--shadow-soft": "0 6px 18px rgba(0,0,0,.5)",
            "--font": 'ui-monospace,"SF Mono",Menlo,Consolas,"PingFang SC",monospace',
            "--node-stroke": "#00E5FF", "--route-line": "rgba(0,229,255,.35)", "--stamina": "#FFB000",
            "--hero-bg": "transparent",
            "--cover-grad": "linear-gradient(135deg,#10202b,#0E1116)",
            "--blank-grad": "linear-gradient(135deg,#13202b,#0E1116)",
            "--toc-bg": "rgba(14,17,22,.82)", "--toc-border": "rgba(0,229,255,.18)",
        },
        "deco": """
body{background-image:linear-gradient(rgba(255,255,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 1px);background-size:28px 28px}
.card{border:1px solid rgba(0,229,255,.16)}
.cover,.sec-img{filter:saturate(1.1)}
""",
    },
    "ukiyo-e": {
        "label": "数字浮世绘", "per_section_accent": False,
        "vars": {
            "--bg": "#F4ECD8", "--card": "#FBF6E9", "--ink": "#2B2B2B", "--sub": "#6B5D4F",
            "--line": "rgba(43,43,43,.16)",
            "--accent": "#1B3B6F", "--accent2": "#C0392B", "--accent-soft": "rgba(27,59,111,.10)",
            "--ok": "#3E7B4F", "--warn": "#C0392B", "--caution": "#B8860B", "--tip": "#3E7B4F",
            "--radius": "3px",
            "--shadow-card": "0 2px 0 rgba(43,43,43,.10),0 6px 16px rgba(43,43,43,.08)",
            "--shadow-soft": "0 6px 16px rgba(43,43,43,.08)",
            "--font": '"Songti SC","Noto Serif SC",Georgia,serif',
            "--node-stroke": "#1B3B6F", "--route-line": "rgba(27,59,111,.30)", "--stamina": "#C0392B",
            "--hero-bg": "linear-gradient(180deg,#F4ECD8,#EFE2C4)",
            "--cover-grad": "linear-gradient(135deg,#EFE2C4,#F4ECD8 60%,#E7D3A8)",
            "--blank-grad": "linear-gradient(135deg,#EFE2C4,#F4ECD8)",
            "--toc-bg": "rgba(244,236,216,.82)", "--toc-border": "rgba(43,43,43,.18)",
        },
        "deco": """
.card{border:1.5px solid rgba(43,43,43,.25)}
.hero p{color:var(--sub)}
""",
    },
    "comic": {
        "label": "漫画格调", "per_section_accent": True,
        "vars": {
            "--bg": "#FFF8E7", "--card": "#FFFFFF", "--ink": "#1A1A1A", "--sub": "#555555",
            "--line": "#1A1A1A",
            "--accent": "#FF3D7F", "--accent2": "#2D9CDB", "--accent-soft": "rgba(255,61,127,.12)",
            "--ok": "#2ECC71", "--warn": "#FF3D3D", "--caution": "#F2A900", "--tip": "#2ECC71",
            "--radius": "14px",
            "--shadow-card": "6px 6px 0 #1A1A1A",
            "--shadow-soft": "4px 4px 0 #1A1A1A",
            "--font": '"Comic Sans MS","Chalkboard SE","PingFang SC",sans-serif',
            "--node-stroke": "#1A1A1A", "--route-line": "#1A1A1A", "--stamina": "#FF3D7F",
            "--hero-bg": "#FFF8E7",
            "--cover-grad": "radial-gradient(circle at 20% 30%,#FFE3EC 0 12px,transparent 13px) 0 0/26px 26px,#FFF8E7",
            "--blank-grad": "radial-gradient(circle at 20% 30%,#FFE3EC 0 10px,transparent 11px) 0 0/24px 24px,#FFFFFF",
            "--toc-bg": "rgba(255,248,231,.85)", "--toc-border": "#1A1A1A",
        },
        "deco": """
.card{border:3px solid #1A1A1A}
.sec-no{border:2px solid #1A1A1A;border-radius:8px}
.donut .d-total{font-family:var(--font)}
""",
    },
    "memphis": {
        "label": "孟菲斯", "per_section_accent": True,
        "vars": {
            "--bg": "#FDF6F0", "--card": "#FFFFFF", "--ink": "#1A1A1A", "--sub": "#555555",
            "--line": "rgba(0,0,0,.12)",
            "--accent": "#FF4D8D", "--accent2": "#00C2CB", "--accent-soft": "rgba(255,77,141,.12)",
            "--ok": "#00C26E", "--warn": "#FF4D4D", "--caution": "#FFC700", "--tip": "#00C26E",
            "--radius": "16px",
            "--shadow-card": "8px 8px 0 #1A1A1A",
            "--shadow-soft": "6px 6px 0 #1A1A1A",
            "--font": '"Poppins","Avenir Next","PingFang SC",sans-serif',
            "--node-stroke": "#1A1A1A", "--route-line": "#1A1A1A", "--stamina": "#FF4D8D",
            "--hero-bg": "#FDF6F0",
            "--cover-grad": "radial-gradient(circle at 30% 30%,#FF4D8D22 0 14px,transparent 15px),radial-gradient(circle at 70% 60%,#00C2CB22 0 14px,transparent 15px),#FDF6F0",
            "--blank-grad": "radial-gradient(circle at 30% 30%,#FF4D8D22 0 12px,transparent 13px),#FFFFFF",
            "--toc-bg": "rgba(253,246,240,.86)", "--toc-border": "#1A1A1A",
        },
        "deco": """
.card{border:2px solid #1A1A1A}
body{background-image:radial-gradient(circle at 12% 18%,#FF4D8D33 0 6px,transparent 7px),radial-gradient(circle at 82% 72%,#00C2CB33 0 6px,transparent 7px),radial-gradient(circle at 50% 90%,#FFC70033 0 5px,transparent 6px);background-size:180px 180px}
""",
    },
    "natural": {
        "label": "自然有机", "per_section_accent": False,
        "vars": {
            "--bg": "#F3F1E7", "--card": "#FBFAF4", "--ink": "#2E3A2E", "--sub": "#5E6B5A",
            "--line": "rgba(46,58,46,.10)",
            "--accent": "#4F7A4F", "--accent2": "#C28E5C", "--accent-soft": "rgba(79,122,79,.12)",
            "--ok": "#5B8C5A", "--warn": "#C0543B", "--caution": "#C28E5C", "--tip": "#5B8C5A",
            "--radius": "24px",
            "--shadow-card": "0 10px 30px rgba(79,122,79,.12)",
            "--shadow-soft": "0 8px 22px rgba(79,122,79,.10)",
            "--font": '"Noto Sans SC","PingFang SC",sans-serif',
            "--node-stroke": "#4F7A4F", "--route-line": "rgba(79,122,79,.30)", "--stamina": "#C28E5C",
            "--hero-bg": "linear-gradient(180deg,#F3F1E7,#E7EAD9)",
            "--cover-grad": "linear-gradient(135deg,#E7EAD9,#F3F1E7 60%,#DCE6D2)",
            "--blank-grad": "linear-gradient(135deg,#E7EAD9,#F3F1E7)",
            "--toc-bg": "rgba(243,241,231,.85)", "--toc-border": "rgba(46,58,46,.10)",
        },
        "deco": """
.hero{position:relative}
.hero::after{content:"";position:absolute;right:-10px;top:30px;width:120px;height:120px;border-radius:60% 40% 55% 45%;background:radial-gradient(circle,rgba(79,122,79,.12),transparent 70%);pointer-events:none}
""",
    },
    "clay": {
        "label": "粘土拟物", "per_section_accent": True,
        "vars": {
            "--bg": "#EAF0FF", "--card": "#F3F7FF", "--ink": "#3A3F55", "--sub": "#6B7194",
            "--line": "rgba(58,63,85,.08)",
            "--accent": "#6C8CFF", "--accent2": "#FF9EC3", "--accent-soft": "rgba(108,140,255,.14)",
            "--ok": "#4CC38A", "--warn": "#FF6B6B", "--caution": "#FFB454", "--tip": "#4CC38A",
            "--radius": "28px",
            "--shadow-card": "8px 8px 16px rgba(150,170,220,.45),-8px -8px 16px rgba(255,255,255,.9)",
            "--shadow-soft": "6px 6px 14px rgba(150,170,220,.40)",
            "--font": '"Quicksand","PingFang SC",sans-serif',
            "--node-stroke": "#6C8CFF", "--route-line": "rgba(108,140,255,.35)", "--stamina": "#FF9EC3",
            "--hero-bg": "linear-gradient(180deg,#EAF0FF,#E0E9FF)",
            "--cover-grad": "linear-gradient(135deg,#E0E9FF,#EAF0FF 60%,#F3E7FF)",
            "--blank-grad": "linear-gradient(135deg,#E0E9FF,#EAF0FF)",
            "--toc-bg": "rgba(234,240,255,.85)", "--toc-border": "rgba(108,140,255,.18)",
        },
        "deco": """
.pdf-btn{border-radius:24px;box-shadow:4px 4px 10px rgba(150,170,220,.5),-4px -4px 10px rgba(255,255,255,.9)}
""",
    },
    "ghibli": {
        "label": "吉卜力治愈", "per_section_accent": False,
        "vars": {
            "--bg": "#EAF4E9", "--card": "#FBFDF6", "--ink": "#3A4A3A", "--sub": "#6A7A66",
            "--line": "rgba(58,74,58,.10)",
            "--accent": "#5B8C5A", "--accent2": "#87B6D6", "--accent-soft": "rgba(91,140,90,.12)",
            "--ok": "#6FAE5F", "--warn": "#D98C4A", "--caution": "#E0B84A", "--tip": "#6FAE5F",
            "--radius": "18px",
            "--shadow-card": "0 8px 24px rgba(91,140,90,.14)",
            "--shadow-soft": "0 6px 18px rgba(91,140,90,.12)",
            "--font": '"Noto Serif SC","Songti SC",Georgia,serif',
            "--node-stroke": "#5B8C5A", "--route-line": "rgba(91,140,90,.30)", "--stamina": "#E0B84A",
            "--hero-bg": "linear-gradient(180deg,#EAF4E9,#DCEFD8)",
            "--cover-grad": "linear-gradient(135deg,#DCEFD8,#EAF4E9 60%,#F0F6E6)",
            "--blank-grad": "linear-gradient(135deg,#DCEFD8,#EAF4E9)",
            "--toc-bg": "rgba(234,244,233,.85)", "--toc-border": "rgba(58,74,58,.10)",
        },
        "deco": """
.hero{position:relative}
.hero::after{content:"";position:absolute;right:0;top:20px;width:160px;height:70px;border-radius:60px;background:radial-gradient(circle at 30% 50%,#fff8,rgba(135,182,214,.25));filter:blur(2px);pointer-events:none}
""",
    },
    "brutal": {
        "label": "新粗野趣味", "per_section_accent": False,
        "vars": {
            "--bg": "#F4F4F0", "--card": "#FFFFFF", "--ink": "#111111", "--sub": "#444444",
            "--line": "#111111",
            "--accent": "#FF5C00", "--accent2": "#3B49DF", "--accent-soft": "rgba(255,92,0,.12)",
            "--ok": "#00C26E", "--warn": "#FF2D2D", "--caution": "#FFC700", "--tip": "#00C26E",
            "--radius": "4px",
            "--shadow-card": "6px 6px 0 #111111",
            "--shadow-soft": "4px 4px 0 #111111",
            "--font": '"Archivo","Arial Black","PingFang SC",sans-serif',
            "--node-stroke": "#111111", "--route-line": "#111111", "--stamina": "#FF5C00",
            "--hero-bg": "#FFE600",
            "--cover-grad": "linear-gradient(135deg,#FFE600,#FFB000 60%,#FF5C00)",
            "--blank-grad": "linear-gradient(135deg,#FFE600,#FFB000)",
            "--toc-bg": "rgba(244,244,240,.88)", "--toc-border": "#111111",
        },
        "deco": """
.card{border:3px solid #111111}
.sec-head h2{background:var(--accent);color:#fff;padding:4px 10px;border-radius:4px}
.sec-no{border:2px solid #111111}
.pdf-btn{background:var(--accent);box-shadow:4px 4px 0 #111111}
""",
    },
}

# 行程类型 → 默认风格：v0.1.0 定稿统一以「苹果极简(apple)」为标准版式（用户确认母版），
# 不再按行程类型自动换肤；如需其它视觉风格需显式 --style 指定。
STYLE_BY_TRIP = {}
# 用户未手动指定 --style 时，一律默认苹果极简（统一 Apple 蓝、860px 居中、毛玻璃目录）
STYLE_BY_TRIP_DEFAULT = "apple"

CUR_STYLE = "apple"
USE_SINGLE_ACCENT = False
STYLE_OVERRIDE = ""


def _style_root(vars_dict: dict) -> str:
    merged = dict(APPLE_VARS)
    merged.update(vars_dict)
    body = "\n".join(f"  {k}:{v};" for k, v in merged.items())
    return f":root{{\n{body}\n}}\n"


def apply_style(style_key: str | None, plan: dict) -> None:
    global CUR_STYLE, USE_SINGLE_ACCENT, STYLE_OVERRIDE
    if style_key and style_key in STYLES:
        key = style_key
    else:
        key = STYLE_BY_TRIP.get((plan.get("style") or "").lower()) or STYLE_BY_TRIP_DEFAULT
        if key not in STYLES:
            key = "apple"
    CUR_STYLE = key
    spec = STYLES[key]
    USE_SINGLE_ACCENT = not spec.get("per_section_accent", True)
    STYLE_OVERRIDE = _style_root(spec.get("vars", {})) + "\n" + (spec.get("deco", "") or "")


# ───────────────────────── 路线地图组件（v0.1.17 策略改判）
# 报告地图层优先级：地图服务 API 真地图 → 备用地图服务 API 备用 → 纯文字兜底；失败即切、不重试不阻塞。
# MAP_MODE 三档：none=不画（默认，走文字衔接卡，已是本册现状）；在线真地图由编排层注入折线后渲染；
#   offline=SVG 手绘示意【已废止，不得作为降级产物输出——用户明确反馈"不用真地图太难看"】。
MAP_MODE = "none"
# 可行性体检关卡：none=关闭（纯零依赖）；advisory=册首提示+板块（默认）；strict=置顶红色强制门禁
FEAS_MODE = "advisory"
FEAS_RESULT: dict | None = None
# ── v0.2.0 出境门禁（第一性原理：能不能成 > 会不会出事 > 花多少 > 玩什么）
# none=不启用（国内默认，境内无准入门槛）；advisory=四灯置于顶部；strict=红灯直接拦停不出行程
GATE_MODE = "auto"
GATE_RESULT: dict | None = None
# 可信度内核（stable / volatile / unknown + 未核验降级角标）
CRED_RESULT = None

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ⚠️ credibility 必须【单独】try。
# 原写法把 credibility 与 gate_card 放在同一个 try 里：
#   try:
#       from credibility import Credibility
#       from gate_card import ...
#       _GATE_AVAILABLE = True
#   except: _GATE_AVAILABLE = False
# 后果：只要 gate_card 缺失（国内技能本就不需要它），
# credibility 的导入也一起失败，CRED_RESULT 恒为 None——
# 【可信度内核被静默关闭】，而 except 只把 _GATE_AVAILABLE 置 False，
# 没人知道可信度内核也没了。这是典型的连带失效。
# 拆成两个独立 try：出境门禁可以没有，可信度内核绝不能被拖累。
try:
    from credibility import Credibility
    _CRED_AVAILABLE = True
except Exception:  # pragma: no cover
    Credibility = None  # type: ignore[assignment]
    _CRED_AVAILABLE = False

try:
    from gate_card import gate_card, gate_html, blocked_page
    _GATE_AVAILABLE = True
except Exception:  # 国内技能不载出境门禁模块，属预期内降级
    gate_card = None      # type: ignore[assignment]
    gate_html = None      # type: ignore[assignment]
    blocked_page = None   # type: ignore[assignment]
    _GATE_AVAILABLE = False

# 摩旅校验模块同样【单独】try —— 理由同上：
# 摩旅是可选能力，绝不能因为它的模块缺失而拖累门禁卡或可信度内核。
try:
    from moto_check import moto_html
    _MOTO_AVAILABLE = True
except Exception:  # pragma: no cover
    moto_html = None      # type: ignore[assignment]
    _MOTO_AVAILABLE = False
# 数据增强通道再单独一个 try —— 缺失只关待核实清单，不关门禁自检。
try:
    from moto_enrich import enrichment_html
    _MOTO_ENRICH_AVAILABLE = True
except Exception:  # pragma: no cover
    enrichment_html = None   # type: ignore[assignment]
    _MOTO_ENRICH_AVAILABLE = False
# v0.1.13 房车/自驾后勤自检，同样独立 try —— 缺失只关后勤卡，不拖累其余板块。
try:
    from rv_check import rv_html
    _RV_AVAILABLE = True
except Exception:  # pragma: no cover
    rv_html = None      # type: ignore[assignment]
    _RV_AVAILABLE = False
_DEST_COORDS: dict = {}  # 名称 -> (lat, lon)


def _load_coords() -> dict:
    global _DEST_COORDS
    if _DEST_COORDS:
        return _DEST_COORDS
    try:
        p = Path(__file__).resolve().parent.parent / "references" / "destinations.json"
        data = json.load(open(p, encoding="utf-8"))
        for d in data.get("destinations", []):
            if isinstance(d, dict) and d.get("name"):
                _DEST_COORDS[d["name"]] = (d.get("lat"), d.get("lon"))
    except Exception:
        pass
    return _DEST_COORDS


def route_map_component(days: list, mode: str = "offline") -> str:
    """返回路线地图 HTML 片段；无坐标或 mode=none 返回空。"""
    if mode == "none" or not days:
        return ""
    coords = _load_coords()
    pts = []
    for d in days:
        city = d.get("city") or ""
        c = coords.get(city)
        if not c or c[0] is None or c[1] is None:
            # 容错：尝试子串匹配
            for name, cc in coords.items():
                if name and (name in city or city in name):
                    c = cc
                    break
        if c and c[0] is not None and c[1] is not None:
            pts.append((city, float(c[0]), float(c[1])))
    if len(pts) < 2:
        return ""  # 单点/无坐标不画地图
    # 等距投影：经度→x，纬度→y（反转）
    lons = [p[2] for p in pts]
    lats = [p[1] for p in pts]
    minx, maxx = min(lons), max(lons)
    miny, maxy = min(lats), max(lats)
    W, H, PAD = 640, 320, 46
    def proj(lon, lat):
        if maxx == minx:
            x = W / 2
        else:
            x = PAD + (W - 2 * PAD) * (lon - minx) / (maxx - minx)
        if maxy == miny:
            y = H / 2
        else:
            y = PAD + (H - 2 * PAD) * (1 - (lat - miny) / (maxy - miny))
        return round(x, 1), round(y, 1)
    proj_pts = [proj(lon, lat) for _, lat, lon in pts]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in proj_pts)
    nodes = "".join(
        f'<g transform="translate({x:.1f},{y:.1f})"><circle r="11" fill="var(--card)" '
        f'stroke="var(--node-stroke)" stroke-width="3"/>'
        f'<text text-anchor="middle" dy="4" style="fill:var(--node-stroke);font-weight:700;font-size:12px">{i+1}</text>'
        f'<text text-anchor="middle" y="26" style="fill:var(--sub);font-size:11px">{esc(c[:6])}</text></g>'
        for i, ((c, _, _), (x, y)) in enumerate(zip(pts, proj_pts))
    )
    # offline SVG 手绘折线（纯本地坐标，不依赖任何在线地图服务）
    return f"""<div class="card"><h3>{icon("🗺")} 路线示意图（离线手绘 · 非地理精确）</h3>
<svg class="rmap" viewBox="0 0 {W} {H}" width="100%" style="max-height:340px">
<path d="{path}" fill="none" stroke="var(--route-line)" stroke-width="3" stroke-linejoin="round"
  stroke-dasharray="2 7" stroke-linecap="round"/>
{nodes}</svg>
<div style="font-size:12px;color:var(--sub);margin-top:6px">＊ 等距投影示意，用于理解城市先后与方位；精确里程/导航请以地图 App 为准。</div></div>"""


# ───────────────────────── 内联 SVG 图标系统（替换 emoji，premium 质感）
# icon() 接收 emoji 或键名，命中则出统一描边 SVG，未命中回退原字符（向后兼容）
ICON_MAP = {
    "🧭": "compass", "🍂": "leaf", "🗓": "calendar", "🚄": "train", "🔍": "search",
    "🌤": "cloud", "🎡": "ticket", "🌡": "info", "📷": "camera", "🎤": "mic",
    "🏨": "bed", "💰": "coin", "🎒": "backpack", "🛡": "shield", "🎯": "target",
    "❄": "snow", "📍": "pin", "📌": "flag", "🚦": "alert", "🏞": "mountain",
    "🆘": "shield", "🪂": "star", "🏔": "mountain", "🌅": "sun", "🌌": "galaxy",
    "🖼": "frame", "🎫": "ticket", "🚫": "ban", "🚇": "train", "🚗": "car",
    "🛏": "bed", "🕐": "clock", "📋": "list", "⏱": "clock", "👥": "users",
    "🌸": "user", "👨‍👩‍👧": "users", "🧓": "user", "🧭": "compass", "🚀": "rocket",
    "✈️": "plane", "🚌": "bus", "📄": "doc", "🏨": "bed", "📈": "trend",
}

SYMBOLS = {
    "compass": '<circle cx="12" cy="12" r="9"/><polygon points="12,7 14,12 12,17 10,12"/>',
    "leaf": '<path d="M5 19c0-7 6-13 14-13 0 8-6 14-14 13z"/><path d="M5 19C9 15 13 11 18 9"/>',
    "calendar": '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 9h16M8 3v4M16 3v4"/>',
    "train": '<rect x="6" y="4" width="12" height="13" rx="2"/><path d="M6 11h12M9 17l-2 3M15 17l2 3"/><circle cx="9" cy="14" r="1"/><circle cx="15" cy="14" r="1"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4-4"/>',
    "cloud": '<path d="M7 18h10a4 4 0 0 0 .5-8 5 5 0 0 0-9.2-1.5A4 4 0 0 0 7 18z"/>',
    "ticket": '<path d="M4 8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2 2 2 0 0 0 0 4 2 2 0 0 1-2 2H6a2 2 0 0 1-2-2 2 2 0 0 0 0-4z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "camera": '<rect x="3" y="7" width="18" height="12" rx="2"/><circle cx="12" cy="13" r="3.5"/><path d="M8 7l1.5-2h5L16 7"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "bed": '<path d="M3 18v-7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7M3 14h18M7 9V7a1 1 0 0 1 1-1h3"/>',
    "coin": '<circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 10h3.2a1.8 1.8 0 0 1 0 3.6H9.5"/>',
    "backpack": '<path d="M8 7a4 4 0 0 1 8 0v3a4 4 0 0 1-8 0z"/><rect x="6" y="10" width="12" height="10" rx="2"/>',
    "shield": '<path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
    "snow": '<path d="M12 2v20M2 12h20M5 5l14 14M19 5L5 19"/>',
    "pin": '<path d="M12 21s7-6 7-11a7 7 0 0 0-14 0c0 5 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    "flag": '<path d="M5 3v18M5 4h11l-2 3 2 3H5"/>',
    "alert": '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
    "mountain": '<path d="M3 20l6-10 4 6 2-3 6 7z"/>',
    "ban": '<circle cx="12" cy="12" r="9"/><path d="M6 6l12 12"/>',
    "car": '<path d="M5 13l1.5-5h11L19 13M4 13h16v4H4z"/><circle cx="8" cy="17" r="1.5"/><circle cx="16" cy="17" r="1.5"/>',
    "sun": '<circle cx="12" cy="13" r="3"/><path d="M3 18h18M5 15l-2 2M19 15l2 2M12 3v3M2 13h3M19 13h3"/>',
    "galaxy": '<path d="M12 3l1.6 4.4 4.4 1.6-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6z"/><circle cx="18" cy="6" r="1"/><circle cx="6" cy="17" r="1"/>',
    "frame": '<rect x="4" y="4" width="16" height="16" rx="2"/><circle cx="10" cy="10" r="2"/><path d="M14 14l4 4"/>',
    "list": '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
    "users": '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.3 2.7-5 6-5s6 1.7 6 5"/><circle cx="17" cy="9" r="2.4"/><path d="M15 20c0-2 1-4 4-4s4 2 4 4"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/>',
    "rocket": '<path d="M12 3c4 2 6 6 6 11l-3 2-3-3h-0l-3 3-3-2c0-5 2-9 6-11z"/><circle cx="12" cy="9" r="1.5"/>',
    "plane": '<path d="M2 12l20-7-7 20-3-8-10-5z"/>',
    "bus": '<rect x="5" y="4" width="14" height="14" rx="2"/><path d="M5 11h14M8 4v4M16 4v4"/><circle cx="8" cy="18" r="1"/><circle cx="16" cy="18" r="1"/>',
    "doc": '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M9 13h6M9 17h6"/>',
    "star": '<path d="M12 3l2.5 6 6.5.5-5 4.5 1.5 6.5L12 17l-5.5 3.5L8 14l-5-4.5 6.5-.5z"/>',
    "trend": '<path d="M3 17l5-6 4 3 6-8"/><path d="M14 6h6v6"/>',
}

ICON_SPRITE = '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>' + "".join(
    f'<symbol id="i-{k}" viewBox="0 0 24 24">{v}</symbol>' for k, v in SYMBOLS.items()
) + '</defs></svg>'


def icon(name: str) -> str:
    sid = ICON_MAP.get(name)
    if not sid:
        return esc(name)
    return f'<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-{sid}"></use></svg>'


# ───────────────────────── 数据可视化签名组件（纯 SVG，零依赖）
def donut_svg(segments: list, size: int = 150, stroke: int = 18) -> str:
    """segments: [(label, value, color)] -> 环形占比图。"""
    total = sum(v for _, v, _ in segments) or 1
    r = (size - stroke) / 2.0
    cx = cy = size / 2.0
    circ = 2 * math.pi * r
    gap = 2  # 段间留白(度换算为周长)
    svg = [f'<svg class="donut" viewBox="0 0 {size} {size}" width="{size}" height="{size}">']
    svg.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="rgba(0,0,0,.05)" stroke-width="{stroke}"/>')
    offset = 0.0
    for label, value, color in segments:
        frac = value / total
        if frac <= 0:
            continue
        len_ = max(0.0, circ * frac - gap)
        svg.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-dasharray="{len_:.1f} {circ - len_:.1f}" stroke-dashoffset="{-offset:.1f}" '
            f'transform="rotate(-90 {cx} {cy})" stroke-linecap="butt"><title>{esc(label)}</title></circle>'
        )
        offset += circ * frac
    svg.append(f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" class="d-total">{esc(_fmt_money(total))}</text>')
    svg.append(f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" class="d-cap">总预算</text>')
    svg.append('</svg>')
    return "".join(svg)


def _fmt_money(v) -> str:
    try:
        return f"¥{int(round(float(v))):,}"
    except Exception:
        return str(v)


def stamina_svg(values: list, w: int = 300, h: int = 92) -> str:
    """逐日强度折线（体力曲线）。values: 每日强度数值。"""
    if not values:
        return ""
    n = len(values)
    pad = 18
    maxv = max(values) or 1
    pts = []
    for i, v in enumerate(values):
        x = pad + (w - 2 * pad) * (i / max(1, n - 1))
        y = h - pad - (h - 2 * pad) * (v / maxv)
        pts.append((x, y))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#FF9500"/>'
        f'<text x="{x:.1f}" y="{(h-4):.0f}" text-anchor="middle" class="sp-x">D{i+1}</text>'
        for i, (x, y) in enumerate(pts)
    )
    area = f"M{pad},{h-pad} " + "L" + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + f" L{w-pad},{h-pad} Z"
    return (
        f'<svg class="stamina" viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="none">'
        f'<defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="var(--stamina)" stop-opacity=".28"/><stop offset="1" stop-color="var(--stamina)" stop-opacity="0"/></linearGradient></defs>'
        f'<path d="{area}" fill="url(#sg)"/>'
        f'<polyline points="{poly}" fill="none" stroke="var(--stamina)" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>'
        f'{dots}</svg>'
    )


def _chain_gap(prev_end: int | None, start: int | None):
    """返回相邻点位的空闲衔接时长字符串（≥10 分钟才显示）。"""
    if prev_end is None or start is None or start < prev_end:
        return None
    g = start - prev_end
    if g < 10:
        return None
    h, m = divmod(g, 60)
    return (f"{h}h{m}m" if h else f"{m}m")


def _parse_hm(t: str):
    """从 '09:00 - 11:00' 或 '09:00' 解析首个/结束分钟数。"""
    if not t:
        return None, None
    t = t.replace("：", ":").strip()
    mm = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", t)
    if mm:
        return int(mm.group(1)) * 60 + int(mm.group(2)), int(mm.group(3)) * 60 + int(mm.group(4))
    s = re.search(r"(\d{1,2}):(\d{2})", t)
    if s:
        v = int(s.group(1)) * 60 + int(s.group(2))
        return v, v
    return None, None


def route_legs_html(days: list, transit: dict | None = None) -> str:
    """点到点路线衔接（替代离线 SVG 示意图）。

    两部分：
    ① 跨城衔接 —— 每段给出 出发→到达名称 + 交通方式 + 里程 + 参考时长 + 参考费用；
    ② 每日点序 —— 按时间轴串起当天点位，并标注相邻点位的「衔接」空闲时长。
    全部来自本地数据（destinations/transit），零外部依赖、合规。
    """
    transit = transit or {}
    # ── ① 跨城衔接 ──
    inter, prev_city = [], None
    for d in days:
        city = d.get("city") or ""
        km = d.get("leg_km")
        mode = d.get("leg_mode")
        if city and prev_city and (km or mode):
            dur = cost = None
            m = transit.get(mode) if mode and isinstance(transit.get(mode), dict) else None
            if m:
                dur = m.get("hours")
                for k in ("price_est", "cost_est", "price_hard_sleeper_est", "price_hard_seat_est"):
                    if m.get(k):
                        cost = m[k]
                        break
            inter.append({"from": prev_city, "to": city, "mode": mode or "—",
                          "km": km, "dur": dur, "cost": cost})
        if city:
            prev_city = city
    inter_html = ""
    if inter:
        items = "".join(
            f'<div class="leg"><div class="leg-route"><b>{esc(x["from"])}</b>'
            f'<span class="leg-arrow">→</span><b>{esc(x["to"])}</b></div>'
            f'<div class="leg-meta">'
            f'<span class="leg-mode">{icon("🚦")} {esc(x["mode"])}</span>'
            + (f'<span>{x["km"]} km</span>' if x["km"] else "")
            + (f'<span>约 {x["dur"]}h</span>' if x["dur"] is not None else "")
            + (f'<span>¥{x["cost"]}</span>' if x["cost"] is not None else "")
            + '</div></div>'
            for x in inter
        )
        inter_html = (f'<div class="card"><h3>{icon("🧭")} 跨城衔接 · 点到点</h3>'
                      f'<div class="legs">{items}</div>'
                      f'<div class="sub" style="margin-top:6px">每段给出出发/到达、交通方式、里程、'
                      f'参考时长与费用；票价/时长以官方实时为准。</div></div>')

    # ── ② 每日点序与衔接时长 ──
    chain_blocks = []
    for d in days:
        slots = [s for s in (d.get("slots") or []) if (s.get("label") or s.get("title"))]
        if len(slots) < 2:
            continue
        rows, prev_end = [], None
        for s in slots:
            name = s.get("label") or s.get("title") or ""
            start, end = _parse_hm(s.get("time", ""))
            gap = _chain_gap(prev_end, start)
            rows.append(f'<div class="chain-row"><span class="chain-dot"></span>'
                        f'<span class="chain-name">{esc(name)}</span>'
                        + (f'<span class="chain-gap">↳ 衔接 {gap}</span>' if gap else "")
                        + '</div>')
            if end is not None:
                prev_end = end
        if rows:
            chain_blocks.append(
                f'<div class="chain-day"><div class="chain-day-h">第 {d.get("day")} 天'
                f' · {esc(d.get("city") or d.get("label") or "")}</div>{"".join(rows)}</div>')
    chain_html = ""
    if chain_blocks:
        chain_html = (f'<div class="card"><h3>{icon("📍")} 每日点序与衔接</h3>'
                     f'{"".join(chain_blocks)}'
                     f'<div class="sub" style="margin-top:6px">按时间轴串起当天点位；'
                     f'「衔接」为相邻点位之间的空闲时长，便于估算转场与用餐窗口。</div></div>')
    return inter_html + chain_html


def elasticity_score(day: dict) -> int:
    """弹性评分★：固定锚点越少越灵活（1-5）。"""
    slots = day.get("slots") or []
    fixed = sum(1 for s in slots if s.get("time"))
    total = max(1, len(slots))
    ratio = fixed / total
    # 锚点占比越低越弹性
    return max(1, min(5, round(5 - ratio * 4)))


# ───────────────────────── 规则型「可执行性体检」阈值（可被 references 覆盖）
def load_feas_rules() -> dict:
    d = load_json(REF / "feasibility_check.json")
    d.setdefault("max_spots_per_day", 6)
    d.setdefault("max_drive_hours", 8)
    d.setdefault("late_hour", 21)
    d.setdefault("altitude_min_days", 3)
    d.setdefault("long_trip_days", 7)
    d.setdefault("transfer_max_spots", 3)
    d.setdefault("tips", {})
    return d


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def load_json(p: Path) -> dict:
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------- 样式与骨架

CSS = """
:root{
  --bg:#F5F5F7; --card:#FFFFFF; --ink:#1D1D1F; --sub:#6E6E73; --line:rgba(0,0,0,.08);
  --accent:#0071E3; --accent2:#5AC8FA; --accent-soft:rgba(0,113,227,.10);
  --ok:#34C759; --warn:#FF3B30; --caution:#FF9500; --tip:#34C759;
  --radius:18px;
  --shadow-card:0 1px 2px rgba(0,0,0,.03),0 4px 14px rgba(0,0,0,.05);
  --shadow-soft:0 8px 22px rgba(0,0,0,.07);
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","PingFang SC","Helvetica Neue","Segoe UI",sans-serif;
  --node-stroke:#0071E3; --route-line:#C7C7CC; --stamina:#FF9500;
  --hero-bg:transparent; --cover-grad:linear-gradient(135deg,#FFE3EC,#E6F0FF 55%,#E9FBF0);
  --blank-grad:linear-gradient(135deg,#EEF3FF,#F2ECFF);
  --toc-bg:rgba(255,255,255,.72); --toc-border:rgba(0,0,0,.08);
}
*{margin:0;padding:0;box-sizing:border-box}

/* 可行性体检门禁横幅（册首，跨风格通用，靠 var 适配深浅色） */
.feas-gate{background:var(--card);border-radius:14px;padding:13px 16px;margin:0 0 14px;font-size:13px;line-height:1.55;border:1px solid var(--line);border-left:5px solid var(--line)}
.feas-gate b{display:block;font-size:14px;margin-bottom:4px;color:var(--ink)}
.feas-gate p{margin:0 0 4px;color:var(--sub)}
.feas-gate ul{margin:4px 0 0 18px;color:var(--ink)}
.feas-gate li{margin:2px 0}
.gate-strict{border-left-color:#FF3B30;background:rgba(255,59,48,.09)}
.gate-advisory{border-left-color:#FF9500;background:rgba(255,149,0,.09)}
.gate-ok{border-left-color:#34C759;background:rgba(52,199,89,.09)}
html{scroll-behavior:smooth;scroll-padding-top:64px}
body{
  background:var(--bg); color:var(--ink);
  font-family:var(--font);
  font-size:13.5px; line-height:1.6; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:860px;margin:0 auto;padding:0 18px 60px}
/* ── 顶部毛玻璃导航 ── */
.toc-bar{
  position:sticky;top:0;z-index:50;
  background:var(--toc-bg);backdrop-filter:saturate(180%) blur(20px);
  -webkit-backdrop-filter:saturate(180%) blur(20px);
  border-bottom:1px solid var(--toc-border);
}
.toc-inner{max-width:860px;margin:0 auto;padding:9px 18px;display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}
.toc-inner::-webkit-scrollbar{display:none}
.toc-inner a{
  flex:none;padding:5px 12px;border-radius:980px;font-size:12px;font-weight:500;
  color:var(--sub);text-decoration:none;background:rgba(118,118,128,.08);transition:all .2s;
}
.toc-inner a:hover,.toc-inner a.on{background:var(--accent);color:#fff}
/* ── Hero ── */
.hero{padding:44px 6px 26px;background:var(--hero-bg)}
.hero-kicker{font-size:13px;font-weight:600;color:var(--accent);letter-spacing:.06em;text-transform:uppercase}
.hero h1{font-size:32px;font-weight:700;letter-spacing:-.02em;margin:6px 0 8px}
.hero p{color:var(--sub);font-size:14px;max-width:560px}
.brandline{margin-top:14px;font-size:11.5px;color:#AEAEB2}
/* ── 配图 ── */
.cover{width:100%;height:184px;border-radius:var(--radius);object-fit:cover;margin-bottom:16px;
  box-shadow:var(--shadow-soft);background:var(--cover-grad)}
.sec-img{width:100%;height:148px;border-radius:14px;object-fit:cover;margin:0 0 10px;
  box-shadow:0 1px 2px rgba(0,0,0,.03),0 6px 16px rgba(0,0,0,.06)}
/* ── 板块 ── */
section{margin:22px 0;scroll-margin-top:70px}
.sec-head{display:flex;align-items:baseline;gap:10px;margin:0 4px 12px}
.sec-no{font-size:12px;font-weight:700;color:var(--accent);letter-spacing:.08em}
.sec-head h2{font-size:21px;font-weight:700;letter-spacing:-.01em}
.sec-head .sub{font-size:12.5px;color:var(--sub)}
.card{
  background:var(--card);border-radius:18px;padding:15px 17px;margin-bottom:10px;
  box-shadow:var(--shadow-card);
}
.card h3{font-size:14.5px;font-weight:650;margin-bottom:8px}
/* ── 景点九宫格（紧凑，无图不占位）── */
.poi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:8px;margin-bottom:8px}
.poi-cell{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:9px 11px;box-shadow:var(--shadow-card)}
.poi-cell .pn{font-size:13.5px;font-weight:650;display:flex;align-items:center;gap:5px}
.poi-cell .pt{margin:5px 0 4px}
.poi-cell .pd{font-size:11.5px;color:var(--sub);line-height:1.45}
/* 景点缩略图：加载失败自动隐藏，绝不占位 / 破图 */
.poi-cell .poi-img{width:100%;height:94px;object-fit:cover;border-radius:9px;margin-bottom:6px;
  background:linear-gradient(135deg,#eef1f6,#e3e8f0);display:block}
/* 封面图说明 */
.cover-cap{font-size:11px;color:#8a8a8e;margin:6px 2px 14px;text-align:right}
/* 图片来源与授权区块 */
.imgcredits li{margin:5px 0;font-size:12px;line-height:1.55}
.imgcredits a{color:var(--accent);text-decoration:none}
.imgcredits a:hover{text-decoration:underline}
/* ── 统计卡组 ── */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px;margin-bottom:14px}
.stat{background:var(--card);border-radius:16px;padding:13px 15px;box-shadow:var(--shadow-card)}
.stat .k{font-size:11px;color:var(--sub);font-weight:600}
.stat .v{font-size:19px;font-weight:700;margin-top:2px;letter-spacing:-.01em}
.stat .v small{font-size:11.5px;font-weight:500;color:var(--sub)}
/* ── 标签 ── */
.tag{display:inline-block;padding:2px 9px;border-radius:980px;font-size:11px;font-weight:600;margin:0 4px 4px 0;background:var(--accent-soft);color:var(--accent)}
.tag.g{background:rgba(52,199,89,.12);color:#248A3D}
.tag.o{background:rgba(255,149,0,.13);color:#C93400}
.tag.r{background:rgba(255,59,48,.11);color:#D70015}
.tag.p{background:rgba(175,82,222,.12);color:#8944AB}
/* ── 警示/贴士 ── */
.note{border-radius:12px;padding:10px 13px;margin:8px 0;font-size:13px}
.note.warn{background:rgba(255,59,48,.06);color:#C00007;border-left:3px solid var(--warn)}
.note.tip{background:rgba(52,199,89,.07);color:#1E7B32;border-left:3px solid var(--tip)}
.note.caution{background:rgba(255,149,0,.08);color:#A05A00;border-left:3px solid var(--caution)}
.note b{font-weight:650}
/* ── 时间线 ── */
.day{margin-bottom:12px}
.day-head{display:flex;align-items:center;gap:10px;margin:14px 0 10px}
.day-no{width:34px;height:34px;border-radius:50%;background:var(--accent);color:#fff;font-weight:700;font-size:13px;display:flex;align-items:center;justify-content:center;flex:none}
.day-head h3{font-size:15.5px;font-weight:650}
.day-head .meta{font-size:12px;color:var(--sub)}
.slot{display:flex;gap:12px;padding:9px 2px;border-top:1px solid var(--line)}
.slot:first-of-type{border-top:none}
.slot .t{flex:none;width:66px;font-size:12px;font-weight:650;color:var(--sa,var(--accent));padding-top:1px}
.slot .c{flex:1}
.slot .c .desc{font-size:12.5px;color:var(--sub);margin-top:1px}
.day-note{margin-top:9px;font-size:12.5px;color:var(--sub);background:rgba(118,118,128,.06);border-radius:10px;padding:8px 12px}
/* ── 列表 ── */
ul.list{list-style:none}
ul.list li{padding:6px 0 6px 20px;position:relative;border-top:1px solid var(--line);font-size:13px}
ul.list li:first-child{border-top:none}
ul.list li::before{content:"";position:absolute;left:4px;top:13px;width:6px;height:6px;border-radius:50%;background:var(--sa,var(--accent));opacity:.75}
ul.list.warn li::before{background:var(--warn)}
ul.list.tip li::before{background:var(--tip)}
/* ── 表格 ── */
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:11.5px;color:var(--sub);font-weight:600;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
.rec{color:var(--accent);font-weight:650}
/* ── 网格 ── */
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
/* ── PDF 按钮 ── */
.pdf-btn{
  position:fixed;right:22px;bottom:22px;z-index:60;border:none;cursor:pointer;
  background:var(--accent);color:#fff;font-size:13px;font-weight:600;
  padding:11px 18px;border-radius:980px;
  box-shadow:0 6px 20px var(--accent-soft);transition:transform .15s,box-shadow .15s;
  font-family:inherit;
}
.pdf-btn:hover{transform:translateY(-2px);box-shadow:0 10px 26px var(--accent-soft)}
.pdf-btn:active{transform:scale(.96)}
/* ── 点到点路线衔接卡（v0.0.10 替代离线 SVG） ── */
.legs{display:flex;flex-direction:column;gap:8px}
.leg{display:flex;justify-content:space-between;align-items:center;gap:12px;
  padding:9px 12px;background:var(--bg);border:1px solid var(--line);border-radius:12px}
.leg-route{font-size:13.5px;display:flex;align-items:center;gap:8px}
.leg-arrow{color:var(--accent);font-weight:700}
.leg-meta{display:flex;gap:14px;align-items:center;font-size:12px;color:var(--sub);white-space:nowrap}
.leg-mode{color:var(--accent);font-weight:600}
.chain-day{margin:10px 0;padding-left:4px}
.chain-day-h{font-size:12.5px;font-weight:700;color:var(--sa,var(--accent));margin-bottom:4px}
.chain-row{display:flex;align-items:center;gap:8px;font-size:13px;padding:3px 0;position:relative;
  padding-left:14px;border-left:2px solid var(--line)}
.chain-dot{position:absolute;left:-5px;top:9px;width:7px;height:7px;border-radius:50%;
  background:var(--sa,var(--accent))}
.chain-name{flex:1}
.chain-gap{font-size:11px;color:var(--tip);background:rgba(52,199,89,.12);
  padding:1px 7px;border-radius:980px;white-space:nowrap}
/* ── 悬浮操作按钮组（FAB，v0.0.10 借鉴同类路书交互） ── */
.fab-stack{position:fixed;right:20px;bottom:20px;z-index:60;display:flex;flex-direction:column;gap:10px}
.fab{width:46px;height:46px;border:none;cursor:pointer;border-radius:50%;
  background:var(--accent);color:#fff;font-size:18px;line-height:46px;text-align:center;
  box-shadow:0 6px 18px var(--accent-soft);transition:transform .15s,box-shadow .15s;font-family:inherit;
  position:relative}
.fab:hover{transform:translateY(-2px);box-shadow:0 10px 24px var(--accent-soft)}
.fab:active{transform:scale(.94)}
.fab span.tip-txt{position:absolute;right:54px;top:50%;transform:translateY(-50%);
  background:rgba(0,0,0,.78);color:#fff;font-size:11px;padding:3px 8px;border-radius:8px;white-space:nowrap;
  opacity:0;pointer-events:none;transition:opacity .15s}
.fab:hover span.tip-txt{opacity:1}
/* ── 行前清单勾选记忆（v0.0.10 localStorage） ── */
label.chk{display:flex;align-items:flex-start;gap:9px;padding:7px 0 7px 4px;
  border-top:1px solid var(--line);font-size:13px;cursor:pointer}
label.chk:first-child{border-top:none}
label.chk input{margin-top:2px;accent-color:var(--accent);flex:none}
label.chk.done span{text-decoration:line-through;color:var(--sub)}
.toast{position:fixed;left:50%;bottom:84px;transform:translateX(-50%);z-index:80;
  background:rgba(0,0,0,.82);color:#fff;font-size:12.5px;padding:8px 16px;border-radius:980px;
  opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:1}
footer{margin-top:34px;padding:20px 0 8px;text-align:center;font-size:11.5px;color:#AEAEB2;border-top:1px solid var(--line)}
/* ── 打印优化 ── */
@media print{
  @page{margin:12mm}
  body{font-size:11px;background:#fff}
  .toc-bar,.pdf-btn,.fab-stack,.toast{display:none!important}
  .card,.stat{box-shadow:none;border:1px solid #E5E5E5;break-inside:avoid}
  section{break-inside:avoid-page;margin:12px 0}
  .hero{padding:16px 0 12px}
  .hero h1{font-size:24px}
  a{color:inherit;text-decoration:none}
}
"""

# ───────────────────────── 设计升级 v0.0.7：差异化组件样式（叠加在 CSS 之上）
CSS2 = """
/* 内联 SVG 图标 */
.i{width:1.12em;height:1.12em;vertical-align:-.18em;fill:none;stroke:currentColor;
  stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}
/* hero 展示质感 */
.hero{position:relative;padding:46px 6px 26px}
.hero-rule{width:56px;height:4px;border-radius:4px;margin:4px 0 0;
  background:linear-gradient(90deg,var(--accent),var(--accent2))}
.hero h1{font-size:33px;font-weight:800;letter-spacing:-.025em;margin:10px 0 8px;line-height:1.12}
/* 板块标题：图标 + 文字对齐 */
.sec-head{display:flex;align-items:center;gap:10px;margin:0 4px 12px;
  border-left:4px solid var(--sa,var(--accent));padding-left:11px}
.sec-head h2{font-size:21px;font-weight:700;letter-spacing:-.01em;
  display:flex;align-items:center;gap:9px;line-height:1.2}
.sec-head h2 .i{width:21px;height:21px;color:var(--sa,var(--accent))}
/* 预算环形图 */
.donut-wrap{display:flex;gap:18px;align-items:center;flex-wrap:wrap;margin-top:4px}
.donut{flex:none}
.donut .d-total{font-size:18px;font-weight:800;fill:var(--ink)}
.donut .d-cap{font-size:9px;fill:var(--sub);letter-spacing:.12em}
.legend{display:flex;flex-direction:column;gap:5px;font-size:12.5px;min-width:148px}
.legend .row{display:flex;align-items:center;gap:8px}
.legend .sw{width:11px;height:11px;border-radius:3px;flex:none}
.legend .lv{color:var(--sub);margin-left:auto;font-variant-numeric:tabular-nums}
/* 体力/弹性曲线 */
.stamina{display:block;margin:8px 0 2px;width:100%}
.stamina .sp-x{font-size:9px;fill:var(--sub)}
.elast{display:inline-flex;align-items:center;gap:4px;margin-left:8px;font-size:11px;color:var(--sub);font-weight:600}
.elast b{color:#FF9500;letter-spacing:1px}
/* 动线示意图 */
.rmap{display:block;margin:6px 0 2px;width:100%}
.rmap .rm-n{font-size:12px;font-weight:700;fill:var(--node-stroke)}
.rmap .rm-c{font-size:10px;fill:var(--sub)}
/* 体检结论徽标 */
.feat-badge{display:inline-block;font-size:11px;font-weight:700;padding:2px 9px;border-radius:980px;margin-left:8px}
.feat-badge.ok{background:rgba(52,199,89,.13);color:#248A3D}
.feat-badge.warn{background:rgba(255,149,0,.14);color:#C93400}
/* 估算透明徽章 */
.est-badge{font-size:10px;font-weight:600;padding:1px 7px;border-radius:980px;
  background:rgba(255,149,0,.14);color:#C93400;margin-left:8px;vertical-align:middle;white-space:nowrap}
/* 动线段标注 */
.rmap .rm-leg{font-size:10px;fill:var(--sub);font-weight:600}
/* UGC 真实反馈卡（v0.0.10 学习 同类方案 可信度分层） */
.ugc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:4px}
.ugc-card{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;
  padding:10px 12px;background:#fff}
.ugc-card.k-pit{border-left-color:#FF3B30}
.ugc-card.k-price{border-left-color:#FF9500}
.ugc-card.k-exp{border-left-color:#34C759}
.ugc-card.k-tip{border-left-color:#0071E3}
.ugc-top{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:5px}
.ugc-kind{font-size:11px;font-weight:700;padding:1px 8px;border-radius:980px;
  background:var(--bg);color:var(--ink)}
.ugc-b{font-size:10px;font-weight:600;padding:1px 7px;border-radius:980px;white-space:nowrap;
  background:var(--bg);color:var(--sub)}
.ugc-b.ugc-real{background:rgba(52,199,89,.15);color:#248A3D}
.ugc-b.ugc-plat{background:rgba(0,113,227,.12);color:#0058B0}
.ugc-b.ugc-blog{background:rgba(110,110,115,.12);color:#6E6E73}
.ugc-b.ugc-chan{background:rgba(255,45,85,.10);color:#C21A4B}
.ugc-b.ugc-rec{background:rgba(255,149,0,.14);color:#C93400}
.ugc-b.ugc-cmt{background:rgba(90,200,250,.16);color:#0071A8}
.ugc-where{font-size:12px;font-weight:600;color:var(--sub);margin-bottom:3px}
.ugc-text{font-size:13px;line-height:1.5;color:var(--ink)}
/* 碳足迹 / 成本对比条（v0.0.11） */
.bar-row{position:relative;display:flex;align-items:center;gap:6px;min-width:130px}
.bar-fill{height:10px;border-radius:6px;flex:none;display:inline-block}
.bar-fill.co2{background:#30D158}
.bar-fill.cost{background:#FF9500}
.bar-row b{font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
"""

JS = """
function savePDF(){window.print();}
function scrollTop(){window.scrollTo({top:0,behavior:'smooth'});}
function toast(msg){var t=document.getElementById('tg-toast');if(!t)return;t.textContent=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show');},1600);}

/* ── 数据-呈现分离：从内嵌 trip-data 重建行程文本/日历（借鉴同类路书） ── */
function tripData(){try{return JSON.parse(document.getElementById('trip-data').textContent);}catch(e){return null;}}
function tripHash(){var d=tripData()||{};var k=(d.title||document.title||'trip')+':'+(d.destinations||[]).join(',');
  var h=0;for(var i=0;i<k.length;i++){h=(h*31+k.charCodeAt(i))>>>0;}return 'tg-'+h.toString(36);}
function pad(n){return (n<10?'0':'')+n;}
function ymd(base,add){var d=new Date(base+'T00:00:00');d.setDate(d.getDate()+(add||0));return d.getFullYear()+pad(d.getMonth()+1)+pad(d.getDate());}
function fmtTime(t){if(!t)return null;var m=t.match(/(\\d{1,2}):(\\d{2})\\s*-\\s*(\\d{1,2}):(\\d{2})/);if(m)return[m[1]+m[2],m[3]+m[4]];var s=t.match(/(\\d{1,2}):(\\d{2})/);return s?[s[1]+s[2],s[1]+s[2]]:null;}

function copyItinerary(){
  var d=tripData();if(!d){toast('数据缺失');return;}
  var L=['【'+ (d.title||'行程') +'】'];
  (d.plan||[]).forEach(function(day){
    L.push('\\n第'+day.day+'天 · '+(day.city||day.label||'') );
    (day.slots||[]).forEach(function(s){
      L.push((s.time?('  '+s.time+' '):'  ')+(s.label||s.title||'') );
    });
  });
  var txt=L.join('\\n');
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(function(){toast('已复制行程');},function(){fallbackCopy(txt);});}
  else{fallbackCopy(txt);}
}
function fallbackCopy(txt){var ta=document.createElement('textarea');ta.value=txt;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{document.execCommand('copy');toast('已复制行程');}catch(e){toast('复制失败，请手动选择');}document.body.removeChild(ta);}

function exportICS(){
  var d=tripData();if(!d){toast('数据缺失');return;}
  var base=d.start_date||d.startDate;
  if(!base){var t=new Date();base=ymd(t.getFullYear()+'-'+pad(t.getMonth()+1)+'-'+pad(t.getDate()),0);}
  var ics=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//AI Travel Guide//ITINERARY//CN','CALSCALE:GREGORIAN'];
  (d.plan||[]).forEach(function(day){
    (day.slots||[]).forEach(function(s){
      var tm=fmtTime(s.time);if(!tm)return;
      var dt=ymd(base,(day.day?day.day-1:0));
      var end=tm[1],st=tm[0];if(end<=st){end=('0000'+(parseInt(end,10)+30)).slice(-4);}
      ics.push('BEGIN:VEVENT','UID:'+tripHash()+'-'+dt+'-'+st+'@ai-travel-guide',
        'DTSTART:'+dt+'T'+st+'00','DTEND:'+dt+'T'+end+'00',
        'SUMMARY:'+(s.label||s.title||'行程'),'END:VEVENT');
    });
  });
  ics.push('END:VCALENDAR');
  var blob=new Blob([ics.join('\\r\\n')],{type:'text/calendar;charset=utf-8'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=(d.title||'行程')+'.ics';a.click();
  toast('已导出 .ics 日历');
}

/* ── 行前清单勾选记忆（localStorage，按行程哈希隔离） ── */
function initPacking(){
  var key=tripHash()+'-pack';var saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}');}catch(e){}
  document.querySelectorAll('label.chk').forEach(function(l){
    var idx=l.getAttribute('data-idx');var cb=l.querySelector('input');
    if(cb&&saved[idx]){cb.checked=true;l.classList.add('done');}
    cb.addEventListener('change',function(){
      var cur={};try{cur=JSON.parse(localStorage.getItem(key)||'{}');}catch(e){}
      if(cb.checked){cur[idx]=1;l.classList.add('done');}else{delete cur[idx];l.classList.remove('done');}
      localStorage.setItem(key,JSON.stringify(cur));
    });
  });
}
window.addEventListener('load',initPacking);
window.addEventListener('scroll',function(){
  var secs=document.querySelectorAll('section[id]');
  var links=document.querySelectorAll('.toc-inner a');
  var y=window.scrollY+90,cur=secs[0];
  secs.forEach(function(s){if(s.offsetTop<=y)cur=s;});
  links.forEach(function(a){a.classList.toggle('on',a.getAttribute('href')==='#'+cur.id);});
});
"""

# 渲染过程收集的板块: (id, 图标, 标题, 副标题)
_registry: list[tuple] = []
# 板块配图 (plan["images"][sid] -> url), 由 render() 注入; 缺失则不出图
_IMAGES: dict = {}
# 紧凑版（轻量）开关：为 True 时精简逐日描述与可选可视化
COMPACT: bool = False
# 是否渲染「行程动线示意图」（自驾/跨城默认开启，单日行程意义不大时可关）
ROUTE_MAP: bool = True
# v0.0.9 新增：风格 / 地图 / 实算 全局开关
FORCED_STYLE: str | None = None
COMPUTE_MODE: str = "none"


def sec_open(sid: str, ico: str, title: str, sub: str = "", badge: str = "") -> str:
    _registry.append((sid, ico, title, sub))
    sa = ACCENT if USE_SINGLE_ACCENT else SECTION_ACCENT.get(sid, ACCENT)
    sub_html = f'<span class="sub">{esc(sub)}</span>' if sub else ""
    badge_html = badge if badge else ""
    img = ""
    url = _IMAGES.get(sid)
    if url:
        img = f'<img class="sec-img" src="{esc(url)}" loading="lazy" alt="{esc(title)}">'
    return (f'<section id="{sid}" style="--sa:{sa}"><div class="sec-head">'
            f'<span class="sec-no">{len(_registry):02d}</span>'
            f'<h2>{icon(ico)}<span>{esc(title)}</span>{badge_html}</h2>'
            f'{sub_html}'
            f'</div>\n{img}')


def build_toc() -> str:
    links = "".join(
        f'<a href="#{sid}">{esc(title)}</a>' for sid, _, title, _ in _registry
    )
    return f'<div class="toc-bar"><nav class="toc-inner">{links}</nav></div>'


def note(text: str, kind: str = "") -> str:
    return f'<div class="note {kind}">{text}</div>' if kind else f'<div class="note">{text}</div>'


def ul(items, cls="list") -> str:
    lis = "".join(f"<li>{it}</li>" for it in items)
    return f'<ul class="{cls}">{lis}</ul>'


def tagify(items, cls="") -> str:
    return "".join(f'<span class="tag {cls}">{esc(t)}</span>' for t in items)


def est_badge() -> str:
    """数据可信度透明徽章：提示本栏数字为估算/需实时核实。"""
    return ('<span class="est-badge" title="里程/票价/开放时间为经验估算，'
            '以官方实时渠道为准">估算 ⓘ</span>')


def real_badge(source: str = "地图服务") -> str:
    """实算徽章：仅当真实 API 成功返回数据时才调用，并标注来源，杜绝假徽章。"""
    return (f'<span class="est-badge" style="background:rgba(52,199,89,.16);color:#1E7B32" '
            f'title="里程/天气来自 {esc(source)} 真实 API（已配置 Key 并成功返回）">实算✓·{esc(source)}</span>')


# ---------------------------------------------------------------- 板块渲染

def _sec_overview(plan: dict) -> str:
    dest = " · ".join(plan.get("destinations") or [])
    style_label = plan.get("style_label", "")
    b = plan.get("budget", {})
    P = []
    P.append(sec_open("overview", "🧭", "行程概览", "先看结论"))
    P.append(f"""<div class="stats">
  <div class="stat"><div class="k">目的地</div><div class="v">{esc(dest)}</div></div>
  <div class="stat"><div class="k">天数</div><div class="v">{plan.get("days")}<small> 天</small></div></div>
  <div class="stat"><div class="k">人员</div><div class="v">{plan.get("people")}<small> 人</small><br><small>{esc(plan.get("composition",""))}</small></div></div>
  <div class="stat"><div class="k">节奏</div><div class="v" style="font-size:15px">{esc(style_label)}</div></div>
  <div class="stat"><div class="k">强度</div><div class="v">{"★"*plan.get("intensity",0)}{"☆"*(5-plan.get("intensity",0))}</div></div>
  <div class="stat"><div class="k">人均预算(估)</div><div class="v">¥{b.get("per_person_total","—")}</div></div>
  <div class="stat"><div class="k">全团合计(估)</div><div class="v">¥{b.get("group_total","—")}</div></div>
</div>""")
    if plan.get("tone"):
        P.append(f'<div class="card"><h3>本次节奏关键词</h3>{tagify(plan["tone"])}'
                 f'<div style="margin-top:8px;font-size:12.5px;color:var(--sub)">'
                 f'节奏画像「{esc(style_label)}」决定每日点位密度与时段长度，逐日动线据此编排。</div></div>')
    return "\n".join(P)


def _sec_season(plan: dict) -> str:
    """季节与气候方案: 从 seasons_climate.json 匹配气候区+季节。"""
    data = load_json(SEASON_DATA)
    season = plan.get("season") or "通用"
    dests = plan.get("destinations") or []
    P = [sec_open("season", "🍂", "季节与气候方案", f"{season}季出行")]
    matched = False
    for d in dests:
        rules = data.get("match_rules", {})
        climate = "south"
        for key in ("plateau_list", "tropical_list", "northwest_list", "southwest_list"):
            if d in rules.get(key, []):
                climate = {"plateau_list": "plateau", "tropical_list": "tropical",
                           "northwest_list": "northwest", "southwest_list": "southwest"}[key]
                break
        region = data.get("regions", {}).get(climate)
        if not region:
            continue
        matched = True
        s = region.get("seasons", {}).get(season)
        if not s:
            continue
        P.append(f"""<div class="card">
  <h3>{esc(d)} · {esc(region["label"])}</h3>
  <div style="margin:2px 0 8px">{tagify([f"气温 {s.get('temp','')}", f"{season}季"], "g")}</div>
  <table>
    <tr><th style="width:64px">穿衣</th><td>{esc(s.get("clothing",""))}</td></tr>
    <tr><th>当季看点</th><td>{esc(s.get("highlight",""))}</td></tr>
    <tr><th>气候风险</th><td>{note(esc(s.get("risk","")), "caution")}</td></tr>
  </table>
</div>""")
    if not matched:
        P.append(note("未匹配到目的地气候区数据，以上为通用季节参考；出行前用 fetch_weather.py 实查天气。", "caution"))
    P.append(note("季节结论绑定出行日期：同一目的地不同月份结论可能完全相反。以上为气候区经验参考，出行前 3 天务必复核实时天气预报。", "tip"))
    return "\n".join(P)


def _sec_route(plan: dict) -> str:
    days = plan.get("plan", [])
    # v0.1.0：只渲染有真实内容的日程；没有任何可渲染日程时整段不出现，杜绝空白栏目
    days = [d for d in days if d.get("slots") or d.get("note")]
    if not days:
        return ""
    P = [sec_open("route", "🗓", "逐日动线", "每天怎么走")]
    # v0.0.10：默认用「点到点路线衔接卡」替代离线 SVG 示意图（数据驱动、合规、更实用）
    if not COMPACT:
        P.append(route_legs_html(days, plan.get("transit")))
    # 可选离线示意图（仅 --map offline 显式开启；不自动开启，避免回归无意义手绘）
    if MAP_MODE == "offline":
        P.append(route_map_component(days, MAP_MODE))
    if not COMPACT:
        vals = [day.get("total_hours") or day.get("spots") or 4 for day in days]
        P.append(f'<div class="card"><h3>{icon("📈")} 体力曲线与弹性</h3>'
                 f'{stamina_svg(vals)}'
                 f'<div style="font-size:12px;color:var(--sub);margin-top:4px">橙色折线为每日强度（点位时长/数量）趋势；'
                 f'每张卡片上的 ★ 为「弹性评分」——固定时间锚点越少越灵活，越容易临时调整。</div></div>')
    for day in days:
        slots_html = []
        for s in day.get("slots", []):
            desc = "" if COMPACT else (s.get("desc") or s.get("note") or "")
            slots_html.append(
                f'<div class="slot"><div class="t">{esc(s.get("time",""))}</div>'
                f'<div class="c"><b>{esc(s.get("label",""))}</b>'
                + (f'<div class="desc">{esc(desc)}</div>' if desc else "")
                + "</div></div>"
            )
        es = elasticity_score(day)
        P.append(f"""<div class="card day">
  <div class="day-head"><div class="day-no">{day.get("day")}</div>
    <div><h3>{esc(day.get("label",""))}</h3>
    <div class="meta">{esc(day.get("city",""))} · 约 {day.get("spots","—")} 个点位 · 约 {day.get("total_hours","—")} 小时
    <span class="elast">弹性 <b>{"★"*es}{"☆"*(5-es)}</b></span></div></div></div>
  {"".join(slots_html)}
  {f'<div class="day-note">{icon("📌")} {esc(day["note"])}</div>' if (not COMPACT and day.get("note")) else ""}
</div>""")
    return "\n".join(P)


def _sec_transit(plan: dict, transit: dict | None) -> str:
    t = transit or plan.get("transit") or {}
    if not t:
        return ""
    badge = real_badge(t.get("distance_source") or "地图服务") if t.get("computed") else est_badge()
    P = [sec_open("transit", "🚄", "交通方案比选", f"{t.get('from','')} → {t.get('to','')}", badge)]
    if t.get("distance_km"):
        P.append(f'<div class="card"><h3>直线距离约 {t.get("distance_km")} km</h3>'
                 + (f'<div class="rec">推荐: {esc(t.get("recommend",""))}</div>'
                    f'<div style="font-size:12.5px;color:var(--sub);margin:4px 0 8px">{esc(t.get("reason",""))}</div>' if t.get("recommend") else "")
                 + "</div>")
    rows = []
    for mode in ("高铁", "普铁", "客车", "轮船", "自驾", "飞机"):
        m = t.get(mode)
        if not m:
            continue
        if mode == "高铁":
            metric, price = f"约 {m['hours']}h", f"¥{m['price_est']}"
        elif mode == "普铁":
            metric, price = f"约 {m['hours']}h", f"硬座 ¥{m['price_hard_seat_est']} / 硬卧 ¥{m['price_hard_sleeper_est']}"
        elif mode == "客车":
            metric, price = f"约 {m['hours']}h", f"¥{m['price_est']}"
        elif mode == "轮船":
            metric, price = f"约 {m['hours']}h", f"¥{m['price_est']}"
        elif mode == "自驾":
            metric, price = f"约 {m['hours']}h", m.get("cost_est") and f"¥{m['cost_est']}" or "—"
        elif mode == "飞机":
            dsc = m.get("price_discount_est", {})
            lo = min(dsc.values()) if dsc else m.get("price_full_est", 0)
            metric, price = f"飞行 {m['hours_flight']}h + 接驳≈{m['hours_total_est']}h", f"折扣估 ¥{lo} 起"
        rows.append(f"<tr><td><b>{mode}</b></td><td>{metric}</td><td>{price}</td>"
                    f"<td style='color:var(--sub)'>{esc(m.get('note',''))[:80]}</td></tr>")
    if rows:
        P.append(f'<div class="card"><table><tr><th>方式</th><th>耗时(估)</th><th>费用(估)</th><th>说明</th></tr>'
                + "".join(rows) + "</table></div>")
    opts = t.get("options") or []
    if opts:
        cards = "".join(
            f'<div class="card"><h3>{esc(o.get("name",""))} <span class="tag g">{esc(o.get("fit",""))}</span></h3>'
            f'<div style="font-size:13px">{esc(o.get("how",""))}</div></div>'
            for o in opts)
        P.append(f'<div class="grid2">{cards}</div>')
    if t.get("disclaimer"):
        P.append(note(esc(t["disclaimer"]), "warn"))
    return "\n".join(P)


def _sec_research(plan: dict, research: dict | None) -> str:
    r = research or {}
    icons = {"transport": "🚦", "spots": "🏞", "food": "🍜", "humanity": "🏛",
             "shops": "🛍", "stay": "🏨", "gear": "🎒", "safety": "🛡", "pitfalls": "⚠️",
             "photo_spots": "📷"}
    titles = {"transport": "交通接驳", "spots": "玩法亮点", "food": "美食",
              "humanity": "人文历史与风土人情", "shops": "商圈与伴手礼",
              "stay": "住宿区域", "gear": "装备", "safety": "安全", "pitfalls": "避坑",
              "photo_spots": "周边美景机位（日出日落观星）"}
    P = []
    for key, items in r.items():
        if not items:
            continue
        ico = icons.get(key, "📌")
        warns = [i for i in items if i.get("kind") == "warn"]
        tips = [i for i in items if i.get("kind") == "tip"]
        norms = [i for i in items if not i.get("kind")]
        if not P:
            P.append(sec_open("research", "🔍", "实地调研", "联网核实过的细节"))
        body = []
        for grp, cls in ((warns, "warn"), (tips, "tip")):
            for i in grp:
                body.append(note(f"<b>{esc(i.get('title',''))}</b> — {esc(i.get('text',''))}", cls))
        for i in norms:
            body.append(f"<li><b>{esc(i.get('title',''))}</b> — {esc(i.get('text',''))}</li>")
        inner = "".join(body)
        if norms:
            inner = f'<ul class="list">{inner}</ul>'
        P.append(f'<div class="card"><h3>{icon(ico)} {esc(titles.get(key,key))}</h3>{inner}</div>')
    return "\n".join(P)


def _sec_ugc(research: dict | None) -> str:
    """实时 UGC 反馈卡（学习 同类方案：社交平台 UGC + 评论挖掘 + 可信度分层）。

    research JSON 中的 "ugc" 键承载结构化条目；无条目或模块缺失时返回空。
    真实联网抓取由宿主 Agent 在规划阶段完成，本函数只做分层可视化。
    """
    if not _render_ugc or not _to_sorted:
        return ""
    r = research or {}
    items = r.get("ugc") if isinstance(r, dict) else None
    if not items:
        return ""
    return sec_open("ugc", "📣", "真实反馈", "踩坑与实测") + "\n" + _render_ugc(_to_sorted(items), wrap_card=False)


def _sec_pitfall(research: dict | None) -> str:
    """避雷 · 别踩这些坑（v0.0.11）：复用 UGC 踩坑层，筛选警示类条目做红系警示。"""
    global _render_pitfalls
    if not _render_ugc or not _to_sorted:
        return ""
    r = research or {}
    items = r.get("ugc") if isinstance(r, dict) else None
    if not items:
        return ""
    pit_kinds = {"踩坑", "避雷", "避坑", "价格陷阱", "坑"}
    pits = [it for it in items if str(it.get("kind", "")) in pit_kinds]
    if not pits:
        return ""
    return sec_open("pitfall", "⚠️", "避雷 · 别踩这些坑", "来自真实反馈的警示") + "\n" + _render_pitfalls(_to_sorted(pits))


def _sec_weather(weather: dict | None) -> str:
    w = weather or {}
    if not w:
        return ""
    # 兼容三种入参：① 扁平 {days,verdict,source}
    #           ② fetch_weather --json 的 {results:[{city,source,days}]}
    #           ③ check_weather --json 的 {results:[{city,verdict,...}]}
    res = w.get("results")
    if res:
        days, srcs, verdicts = [], [], []
        for r in res:
            days.extend(r.get("days") or [])
            if r.get("source"):
                srcs.append(r["source"])
            if r.get("verdict"):
                verdicts.append(r["verdict"])
        w = {
            "days": days,
            "source": srcs[0] if srcs else w.get("source"),
            "verdict": verdicts[0] if verdicts else w.get("verdict"),
            "summary": w.get("summary"),
            "advice": w.get("advice"),
        }
    verdict = w.get("verdict", "")
    style = {"ok": ("适宜出行", OK), "caution": ("需谨慎", CAUTION),
             "indoor_rewrite": ("建议改室内", "#0071E3"), "not_recommended": ("不建议按原计划", BAD)}
    label, color = style.get(verdict, ("", "#6E6E73"))
    src = w.get("source")
    badge = real_badge(src) if src else est_badge()
    P = [sec_open("weather", "🌤", "天气可行性预检", "户外行程先过这一关", badge)]
    if label:
        P.append(note(f"<b>预检结论：{label}</b>　{esc(w.get('summary',''))}",
                      {"ok": "tip", "caution": "caution", "indoor_rewrite": "", "not_recommended": "warn"}.get(verdict, "")))
    rows = []
    for d in w.get("days", []):
        rows.append(f"<tr><td>D{d.get('day')}</td><td>{esc(d.get('wmo_text',''))}</td>"
                    f"<td>{d.get('t_min','')}~{d.get('t_max','')}°C</td><td>降水 {d.get('precip_mm','')}mm / {d.get('precip_prob','')}%</td>"
                    f"<td>风速 {d.get('wind_kmh','')}km/h</td><td>{esc(d.get('verdict',''))}</td></tr>")
    if rows:
        P.append('<div class="card"><table><tr><th>日</th><th>天气</th><th>气温</th><th>降水</th><th>风速</th><th>判定</th></tr>'
                 + "".join(rows) + "</table></div>")
    advice = w.get("advice")
    if advice:
        P.append(f'<div class="card"><h3>应对建议</h3>{ul(advice if isinstance(advice, list) else [advice])}</div>')
    return "\n".join(P)


def _sec_weather_contingency(weather: dict | None) -> str:
    """天气突变 Plan B：仅在天气预报【明确指出】恶劣天气时才渲染，且内容必须本地化、
    具体到地址与改安排（来自 plan.weather.contingency），绝不写通用模板敷衍。"""
    w = weather or {}
    days = w.get("days") or []
    if not days:
        return ""
    # —— 明确信号：雨/雷、高温≥35、低温≤0、大风≥40、强霾雾 ——
    bad = any(
        (d.get("precip_prob") or 0) >= 60
        or "雨" in str(d.get("wmo_text", ""))
        or "雷" in str(d.get("wmo_text", ""))
        or (isinstance(d.get("t_max"), (int, float)) and d.get("t_max") >= 35)
        or (isinstance(d.get("t_min"), (int, float)) and d.get("t_min") <= 0)
        or (d.get("wind_kmh") or 0) >= 40
        for d in days)
    cont = w.get("contingency")  # 本地化、含地址与改安排的具体方案
    if not (bad and cont):
        return ""
    P = [sec_open("wxb", "🧭", "天气突变预案 · Plan B", "仅在有明确天气变化时给出本地化改安排")]
    for c in cont:
        where = c.get("where", "")
        do = c.get("do", "")
        P.append(f'<div class="card"><h3>{icon(c.get("icon", "🌧"))} {esc(c.get("label", ""))}</h3>'
                 + (f'<div class="sub" style="margin-bottom:4px"><b>地点</b>：{esc(where)}</div>' if where else "")
                 + (f'<div class="pd">{esc(do)}</div>' if do else "")
                 + '</div>')
    note_txt = w.get("contingency_note", "")
    if note_txt:
        P.append(f'<div class="sub" style="margin-top:6px">{esc(note_txt)}</div>')
    return "\n".join(P)


def _sec_carbon(plan: dict, transit: dict | None) -> str:
    """绿色出行 · 碳足迹与成本双轴对比（v0.0.11）：汇总跨城里程后对比各交通方式。"""
    days = plan.get("plan") or []
    total_km = sum((d.get("leg_km") or 0) for d in days)
    if total_km <= 0:
        return ""
    data = load_json(CARBON_DATA)
    fac = data.get("factors", {})
    if not fac:
        return ""
    calc, max_co2, max_cost = [], 0.0, 0.0
    for name, f in fac.items():
        g = f.get("gco2_per_km", 0)
        c = f.get("cost_per_km", 0)
        sp = f.get("ref_speed_kmh", 60)
        co2 = total_km * g / 1000.0
        cost = total_km * c
        hours = total_km / sp if sp else 0
        calc.append((name, f.get("icon", ""), co2, cost, hours))
        max_co2 = max(max_co2, co2)
        max_cost = max(max_cost, cost)
    rows = []
    for name, ic, co2, cost, hours in calc:
        co2w = (co2 / max_co2 * 100) if max_co2 else 0
        costw = (cost / max_cost * 100) if max_cost else 0
        rows.append(
            f'<tr><td>{ic} {esc(name)}</td>'
            f'<td><div class="bar-row"><span class="bar-fill co2" style="width:{co2w:.0f}%"></span>'
            f'<b>{co2:.1f} kg</b></div></td>'
            f'<td><div class="bar-row"><span class="bar-fill cost" style="width:{costw:.0f}%"></span>'
            f'<b>¥{cost:.0f}</b></div></td>'
            f'<td>{hours:.1f}h</td></tr>'
        )
    P = [sec_open("carbon", "🌱", "绿色出行 · 碳足迹与成本对比",
                  f"基于跨城总里程 {total_km:.0f} km 的估算{est_badge()}")]
    P.append('<div class="card"><table><tr><th>方式</th><th>碳排放(kg CO₂e)</th>'
             '<th>参考成本(¥)</th><th>约耗时</th></tr>'
             + "".join(rows) + "</table>"
             f'<div class="sub" style="margin-top:6px">{esc(data.get("note", ""))}</div></div>')
    return "\n".join(P)


def _sec_poi(plan: dict, poi: dict) -> str:
    """景点攻略与门票：紧凑九宫格，实景缩略图（失败自动隐藏不占位），门票+一句话必看。"""
    dests = plan.get("destinations") or []
    imgs = plan.get("images") or {}
    cells = []
    for d in dests:
        spots = (poi.get(d) or {}).get("spots") if isinstance(poi.get(d), dict) else None
        if not spots:
            continue
        for s in spots:
            name = s.get("name", s.get("景点", ""))
            ticket = s.get("ticket") or s.get("门票") or "现场确认"
            must = s.get("must") or s.get("一句话") or ""
            im = imgs.get(name)
            img_html = ""
            if isinstance(im, dict) and im.get("url"):
                img_html = (f'<img class="poi-img" loading="lazy" src="{esc(im["url"])}" '
                            f'alt="{esc(name)}" onerror="this.style.display=\'none\'">')
            cells.append(
                f'<div class="poi-cell">{img_html}'
                f'<div class="pn">{icon("📍")}{esc(name)}</div>'
                f'<div class="pt">{tagify([esc(ticket)])}</div>'
                + (f'<div class="pd">{esc(must)}</div>' if must else "")
                + '</div>')
    if not cells:
        return ""
    out = sec_open("poi", "🎡", "景点攻略与门票", "门票 · 必看 · 实景图")
    return out + f'<div class="poi-grid">{"".join(cells)}</div>'


def _sec_image_credits(plan: dict) -> str:
    """图片来源与授权：集中列示所有外链实景图，满足 CC 自由授权署名要求。"""
    cover = plan.get("cover_url")
    cover_credit = plan.get("cover_credit") or {}
    imgs = plan.get("images") or {}
    rows = []
    if cover:
        title = cover_credit.get("title") or "封面实景图"
        file_url = cover_credit.get("file") or ""
        lic = cover_credit.get("license") or "自由授权（详见 Wikimedia Commons 文件页）"
        author = cover_credit.get("author") or "Wikimedia Commons"
        link = (f' · <a href="{esc(file_url)}" target="_blank" rel="noopener">文件页 ↗</a>'
                if file_url else "")
        rows.append(f'<li>🖼 <b>{esc(title)}</b>（封面）— 作者 {esc(author)} · 许可 {esc(lic)}{link}</li>')
    for name, im in imgs.items():
        if not isinstance(im, dict):
            continue
        file_url = im.get("file") or ""
        lic = im.get("license") or "自由授权（详见 Wikimedia Commons 文件页）"
        author = im.get("author") or "Wikimedia Commons"
        link = (f' · <a href="{esc(file_url)}" target="_blank" rel="noopener">文件页 ↗</a>'
                if file_url else "")
        rows.append(f'<li>📍 <b>{esc(name)}</b> — 作者 {esc(author)} · 许可 {esc(lic)}{link}</li>')
    if not rows:
        return ""
    out = sec_open("imgcredits", "📷", "图片来源与授权", "Wikimedia Commons · 自由授权")
    inner = ('<div style="font-size:12.5px;line-height:1.55;margin-bottom:6px">'
             '本小册子中的实景照片均来自 <b>Wikimedia Commons</b>（维基共享资源），采用 CC0 / CC BY-SA 等自由授权，可合规使用。'
             '按自由授权要求逐一署名来源与许可，点击「文件页 ↗」可核验原作者与许可条款。'
             '若图片因网络受限未能加载，页面会自动隐藏空图框，不影响阅读。</div>')
    return out + (f'<div class="imgcredits card">{inner}'
                  f'<ul style="margin:4px 0 0;padding-left:18px">{"".join(rows)}</ul></div>')


def _sec_stay(plan: dict) -> str:
    s = plan.get("stay") or {}
    b = plan.get("budget") or {}
    if not s:
        return ""
    if b.get("nights") == 0:
        out = sec_open("stay", "🏨", "住宿安排", "当天来回")
        return out + (f'<div class="card"><h3>{icon("🛏")} 当天来回，无需住宿</h3>'
                      f'<div style="font-size:13px">近程圈行程按 0 晚计——预算中住宿项为 ¥0，'
                      f'省下的房费可用于升级餐饮或打车。若想改住一晚看夜景/日出，告诉我可重新编排。</div></div>')
    P = [sec_open("stay", "🏨", "住宿安排", "按房间数而非人数")]
    P.append(f"""<div class="card"><h3>{s.get("rooms")} 间 · {" / ".join(s.get("room_types", []))}</h3>
<div style="font-size:13px;margin:4px 0 6px">{esc(s.get("rationale",""))}</div>
{ul(s.get("tips", [])) if s.get("tips") else ""}
</div>""")
    return "\n".join(P)


def _sec_budget(plan: dict) -> str:
    b = plan.get("budget") or {}
    g = b.get("group", {}) or {}
    P = [sec_open("budget", "💰", "预算安排", "估算口径透明", est_badge())]
    # ── 环形占比图 + 图例 ──
    if g:
        segs = []
        legend = []
        for k, v in g.items():
            try:
                vv = int(round(float(v)))
            except Exception:
                vv = 0
            color = BUDGET_COLORS.get(k, "#8E8E93")
            segs.append((k, vv, color))
            legend.append(f'<div class="row"><span class="sw" style="background:{color}"></span>'
                          f'{esc(k)}<span class="lv">¥{vv:,}</span></div>')
        P.append(f'<div class="card"><div class="donut-wrap">{donut_svg(segs)}'
                 f'<div class="legend">{"".join(legend)}</div></div></div>')
    rows = []
    for k in g:
        rows.append(f"<tr><td>{k}</td><td>¥{g[k]}</td><td>¥{(b.get('per_person') or {}).get(k,0)}</td>"
                    f"<td>{round(g[k]/max(sum(g.values()),1)*100)}%</td></tr>")
    P.append(f"""<div class="card"><table>
<tr><th>分项</th><th>最低</th><th>常规</th><th>占比</th></tr>
{"".join(rows)}
<tr><td><b>合计</b></td><td class="rec">¥{b.get("group_total")}</td><td class="rec">¥{b.get("per_person_total")}</td><td>100%</td></tr>
</table>
<div style="font-size:12px;color:var(--sub);margin-top:8px">{esc(b.get("note",""))} {esc(b.get("lodging_basis",""))}</div></div>""")
    # ── AA 人均分摊（人数 > 1 时显式展示）──
    people = plan.get("people") or 1
    if isinstance(people, str):
        try:
            people = int(people)
        except Exception:
            people = 1
    if people and people > 1:
        P.append(note(f"<b>AA 分摊</b>：{people} 人平摊，每人约 ¥{b.get('per_person_total')}（全团合计 ¥{b.get('group_total')}）。"
                      f" 大项如住宿/租车按房间或车辆数计，已在「最低/常规」两档中区分全团与人均。", "tip"))
    ub = (plan.get("budget") or {}).get("user_budget")
    if ub:
        bd = plan["budget"]
        within = bd.get("budget_status") == "within"
        verdict = "✅ 在预算内" if within else "⚠️ 已超出预算"
        P.append(note(f"<b>预算核对</b>：你的预算 ¥{ub}，估算总额 ¥{bd.get('group_total')}，"
                      f"差额 ¥{abs(bd.get('budget_diff', 0))}（{verdict}）。"
                      + ("" if within else " 可降住宿/餐饮档位或减天数平衡。"), "tip" if within else "warn"))
    return "\n".join(P)


def _sec_packing(plan: dict) -> str:
    data = load_json(PACKING_DATA)
    season = plan.get("season")
    style = plan.get("style", "")
    mode_key = {"roadtrip": "自驾", "moto": "摩旅", "rv": "房车", "cycling": "骑行",
                "hiking": "徒步", "extreme": "极限运动", "nature": "自然美景专线"}.get(style, "公共交通")
    P = [sec_open("packing", "🎒", "行前准备清单", "避免遗漏造成不便")]
    P.append(f'<div class="grid2">')
    blocks = [("通用必备", data.get("base", {}).get("items", []), "")]
    if data.get("by_mode", {}).get(mode_key):
        blocks.append((f"{mode_key}专项", data["by_mode"][mode_key], ""))
    if season and data.get("by_season", {}).get(season):
        blocks.append((f"{season}季加项", data["by_season"][season], ""))
    for title, items, cls in blocks:
        if items:
            P.append(f'<div class="card"><h3>{esc(title)}</h3>{ul(items, cls)}</div>')
    P.append("</div>")
    tl = data.get("prep_timeline", {}).get("items", [])
    if tl:
        P.append(f'<div class="card"><h3>{icon("⏱")} {esc(data["prep_timeline"].get("label","行前时间线"))}</h3>{ul(tl)}</div>')
    return "\n".join(P)


def _sec_safety(plan: dict) -> str:
    """安全与应急（v0.1.0 合并版）：把「安全提醒 + 应急预案」合成一个板块，
    优先用 plan.safety 的本地化、可落地最优解；无则退回精简通用版，绝不堆模板。"""
    s = plan.get("safety") or {}
    P = [sec_open("safety", "🛡", "安全与应急", "只给本地化、可落地的最优解")]
    blocks = s.get("blocks") or []
    if blocks:
        P.append('<div class="grid2 safety-grid">')
        for b in blocks:
            ic = b.get("icon", "🛡")
            t = b.get("title", "")
            items = b.get("items", [])
            P.append(f'<div class="card"><h3>{ic} {esc(t)}</h3>{ul(items)}</div>')
        P.append("</div>")
    em = s.get("emergency") or {}
    if em:
        hot = em.get("hotline") or []
        P.append(f'<div class="card"><h3>🆘 {esc(em.get("title", "紧急备用"))}</h3>'
                 f'{ul(em.get("items", []))}'
                 + (f'<div class="sub" style="margin-top:5px"><b>关键电话</b>：{" · ".join(esc(h) for h in hot)}</div>' if hot else "")
                 + '</div>')
    return "\n".join(P)


def _sec_outbound(plan: dict, oc=None) -> str:
    """出境 4 维约束板块（准入 / 货币 / 合规文化 / 领事安全）。

    定位纪律：这些不是「出境知识科普」，而是【约束】——每一条都必须能回答
    「它如何改变我的行程安排」，否则不进册。例如靠左行驶只写"影响自驾与
    路口观察"，不写一段日本地理介绍。
    """
    try:
        if oc is None:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from outbound_constraints import OutboundConstraints
            oc = OutboundConstraints(plan.get("destinations") or [])
        if not getattr(oc, "outbound", False):
            return ""
    except Exception:
        return ""

    P = [sec_open("outbound", "🌐", "出境约束与在地生存",
                  "准入 · 货币 · 合规文化 · 领事安全（每条都直接影响行程安排）")]

    # ① 货币与购买力 —— 直接影响预算与消费决策
    m = oc.money()
    if m:
        rows = []
        if m.get("currency"):
            rows.append(f'<b>货币</b>　{esc(m["currency"])}')
        if m.get("rate_note"):
            rows.append(f'<b>汇率量级</b>　{esc(m["rate_note"])}')
        if m.get("time_diff"):
            rows.append(f'<b>时差</b>　{esc(m["time_diff"])}'
                        + (f'（{esc(m["dst"])}）' if m.get("dst") else ""))
        if m.get("card"):
            rows.append(f'<b>刷卡/支付</b>　{esc(m["card"])}')
        if m.get("mobile_pay"):
            rows.append(f'<b>手机支付</b>　{esc(m["mobile_pay"])}')
        if m.get("tipping"):
            rows.append(f'<b>小费</b>　{esc(m["tipping"])}')
        li = "".join(f"<li>{r}</li>" for r in rows)
        P.append(f'<div class="card"><h3>💱 货币与购买力<span class="feat-badge tip">影响预算与支付方式</span></h3>'
                 f'<ul class="kv">{li}</ul>'
                 f'<p class="sub" style="margin:6px 0 0">汇率为量级参考，出发前请查当日汇率；'
                 f'境外刷卡需提前开通境外交易额度。</p></div>')

    # ③ 合规与文化 —— 违反可能罚款/拒入境
    c = oc.culture()
    if c:
        cards = []
        if c.get("driving"):
            cards.append(f'<div class="card"><h3>🚗 行驶与用电</h3>'
                         f'<p class="sub" style="margin:0 0 6px">{esc(c["driving"])}</p>'
                         f'<p class="sub" style="margin:0">影响：自驾需靠对应侧行驶、'
                         f'充电设备须匹配电压与插头。</p></div>')
        if c.get("taboos"):
            tlis = "".join(f"<li>{esc(t)}</li>" for t in c["taboos"])
            cards.append(f'<div class="card"><h3>⚠️ 禁忌与礼仪（硬规矩）</h3>'
                         f'<ul class="list">{tlis}</ul>'
                         f'<p class="sub" style="margin:6px 0 0">违反可能引发罚款或被拒绝入境，'
                         f'不是「礼貌建议」。</p></div>')
        if c.get("dress"):
            cards.append(f'<div class="card"><h3>👗 着装要求</h3>'
                         f'<p class="sub" style="margin:0">{esc(c["dress"])}</p></div>')
        if c.get("transport"):
            apps = ("；必装：" + "、".join(c["apps"])) if c.get("apps") else ""
            cards.append(f'<div class="card"><h3>🚇 当地交通与 App</h3>'
                         f'<p class="sub" style="margin:0 0 6px">{esc(c["transport"])}</p>'
                         f'<p class="sub" style="margin:0">{esc(apps)}</p>'
                         f'<p class="sub" style="margin:6px 0 0">影响：每日动线的换乘方式与耗时估算'
                         f'按此口径排，不套用国内习惯。</p></div>')
        if cards:
            P.append('<div class="grid2">')
            P.extend(cards)
            P.append("</div>")

    # ④ 领事与制度安全 —— 风险锚点 + 核验渠道
    s = oc.safety()
    rows = []
    if s.get("severity"):
        rows.append(f'<b>治安提示</b>　{esc(s["severity"])}')
    if s.get("scams"):
        rows.append(f'<b>常见骗局</b>　{esc("、".join(s["scams"]))}')
    if s.get("natural"):
        rows.append(f'<b>自然灾害与季节</b>　{esc("；".join(s["natural"]))}')
    if rows:
        li = "".join(f"<li>{r}</li>" for r in rows)
        P.append(f'<div class="card"><h3>🛡 在地安全锚点'
                 f'<span class="feat-badge tip">影响行程时段与区域</span></h3>'
                 f'<ul class="kv">{li}</ul>'
                 f'<p class="sub" style="margin:6px 0 0">核验渠道：'
                 f'{esc(s.get("verify", "中国领事服务网 cs.mfa.gov.cn"))}。</p></div>')

    # 高风险区域硬提示
    flags = oc.risk_flags()
    if flags:
        items = "".join(f'<li><b>{esc(f.get("region"))}</b> — {esc(f.get("level"))}'
                        f'（{esc(f.get("_source"))}）</li>' for f in flags)
        P.append(f'<div class="card" style="border:1px solid var(--warn)">'
                 f'<h3>🚫 目的地安全提醒（外交部）</h3><ul class="kv">{items}</ul></div>')

    # 领事应急卡 —— 必含，是出境最容易忘又最关键的一张
    P.append('<div class="card" style="border:1px solid var(--warn)">'
             '<h3>🆘 领事保护与应急（存手机 + 抄一份纸质）</h3>'
             '<ul class="list">'
             '<li><b>中国领事保护</b>　12308（境外拨 +86-10-12308）</li>'
             '<li><b>当地紧急电话</b>　以当地官方公布为准，出发前查中国领事服务网</li>'
             '<li><b>旅行保险救援</b>　保存承保方24 小时热线与保单号</li>'
             '</ul>'
             '<p class="sub" style="margin:6px 0 0">以上为中国统一口径；目的地号码不做猜测。</p></div>')
    return "\n".join(P)


def _nearest_hub(lat: float, lon: float):
    """返回 (枢纽名, 距离km) 最近邻，用于高反就近就医参考。"""
    best, best_d = None, 1e12
    for name, (hlat, hlon) in MED_HUBS.items():
        import math
        r = 6371.0
        p1, p2 = math.radians(lat), math.radians(hlat)
        dp = math.radians(hlat - lat)
        dl = math.radians(hlon - lon)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        d = 2 * r * math.asin(min(1, math.sqrt(a)))
        if d < best_d:
            best_d, best = d, name
    return best, best_d


def _sec_altitude(plan: dict) -> str:
    """高反应急与就近就医预案（v0.0.11）：命中高原目的地时自动出现。"""
    dests = plan.get("destinations") or []
    data = load_json(ALTITUDE_DATA)
    # 命中高原关键词
    matched = []
    for name in dests:
        ns = str(name)
        for kw in HIGH_KEYWORDS:
            if kw in ns:
                matched.append(ns)
                break
    if not matched and not plan.get("has_high_altitude"):
        return ""
    # 用目的地坐标做就近就医参考
    dest_json = load_json(REF / "destinations.json")
    coord_map = {}
    for d in dest_json.get("destinations", []):
        lat, lon = d.get("lat"), d.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            coord_map[d.get("name")] = (lat, lon)
    hub_lines = []
    seen = set()
    for m in matched:
        base = m
        for kw in HIGH_KEYWORDS:
            if kw in m:
                base = kw
                break
        if base in seen:
            continue
        seen.add(base)
        if base in coord_map:
            hub, dist = _nearest_hub(*coord_map[base])
            hub_lines.append(f"{m} → 就近就医参考：{hub}（约 {dist:.0f} km）")
        else:
            hub_lines.append(f"{m} → 抵达后定位最近三甲医院（用地图 App 检索）")
    P = [sec_open("altitude", "🩺", "高反应急与就近就医", "高原线 / 自驾线必备")]
    grades = data.get("grades", [])
    for g in grades:
        lvl = esc(g.get("level", ""))
        sym = esc("、".join(g.get("symptoms", [])))
        P.append(f'<div class="card"><h3>⛰ {lvl}高反</h3>'
                 f'<div class="sub" style="margin-bottom:4px">表现：{sym}</div>'
                 f'{ul(g.get("action", []), "warn")}</div>')
    meds = data.get("meds", [])
    if meds:
        P.append(f'<div class="card"><h3>💊 常备药与物资</h3>{ul(meds)}</div>')
    if hub_lines:
        P.append(f'<div class="card"><h3>🏥 就近就医参考</h3>{ul(hub_lines)}</div>')
    P.append(f'<div class="sub" style="margin-top:6px">{esc(data.get("note", ""))}</div>')
    return "\n".join(P)


def _sec_extreme_nature(plan: dict) -> str:
    """极限玩法库 / 自然美景专线板块, 仅 extreme / nature 画像渲染。"""
    style = plan.get("style", "")
    if style not in ("extreme", "nature"):
        return ""
    data = load_json(EXTREME_DATA)
    P = []
    if style == "extreme":
        P.append(sec_open("extreme", "🪂", "极限玩法库", "红牛时刻 · 安全红线优先"))
        blob = " ".join(str(x) for x in (plan.get("tone", []) + (plan.get("destinations") or [])
                                          + (plan.get("prefs") and [str(p) for p in plan["prefs"]] or [])))
        keywords = [("冲浪", "surfing"), ("滑雪", "skiing"), ("跳伞", "skydiving"),
                    ("骑马", "horseback"), ("射击", "shooting"), ("攀岩", "climbing"),
                    ("速降", "zipline_rappelling"), ("滑索", "zipline_rappelling"),
                    ("溪降", "zipline_rappelling"), ("蹦极", "bungee")]
        show_keys = [v for w, v in keywords if w in blob] or ["surfing", "skydiving", "bungee", "climbing"]
        for k in show_keys:
            s = data.get("extreme_sports", {}).get(k)
            if not s:
                continue
            P.append(f"""<div class="card">
  <h3>{esc(s['label'])} <span class="tag r">极限</span></h3>
  <table>
    <tr><th style="width:52px">基地</th><td>{esc(" / ".join(s.get("bases", [])[:3]))}</td></tr>
    <tr><th>季节</th><td>{esc(s.get("season",""))}</td></tr>
    <tr><th>费用</th><td>{esc(s.get("cost",""))}</td></tr>
    <tr><th>装备</th><td>{esc("；".join(s.get("gear", [])))}</td></tr>
  </table>
  {note("<b>安全红线</b>：" + esc("；".join(s.get("risk", [])[:3])), "warn")}
  {note("<b>天气停表</b>：" + esc(s.get("weather_redline","")), "caution")}
</div>""")
        P.append(note("极限运动共同铁律：只选持证场地；买含高风险运动条款的专项意外险；告知书如实申报健康史；装备检查参与确认；天气窗口即生命线——靠谱的运营方会主动停，硬拉你上的要警惕。", "warn"))
    else:  # nature
        P.append(sec_open("nature", "🏔", "自然美景专线", "景观走廊 + 补给应急"))
        nm = data.get("nature_routes", {})
        if nm.get("principles"):
            P.append(f'<div class="card"><h3>规划原则</h3>{ul(nm["principles"])}</div>')
        for mk, block in nm.get("by_mode", {}).items():
            cards = []
            for r in block.get("routes", [])[:3]:
                hard = ' <span class="tag r">硬核</span>' if r.get("hard") else ""
                cards.append(f"""<div class="card"><h3 style="font-size:13.5px">{esc(r['name'])}{hard}</h3>
  <div style="font-size:12.5px;margin-bottom:5px">{esc(r['path'])}</div>
  {tagify([f"最佳季 {r.get('season','')}"])}
  <div style="font-size:12px;color:var(--sub);margin-top:5px">看点: {esc(r.get("highlight",""))}</div></div>""")
            P.append(f'<div class="card"><h3>{icon("🚵")} {esc(block.get("label",""))} · 推荐线路</h3>'
                     f'<div class="grid2">{"".join(cards)}</div></div>')
            P.append(f"""<div class="card"><h3>补给与应急 · {esc(block.get("label",""))}</h3>
  <table><tr><th style="width:52px">补给</th><td>{esc("；".join(block.get("supply", [])))}</td></tr>
  <tr><th>应急</th><td>{esc("；".join(block.get("emergency", [])))}</td></tr></table></div>""")
    return "\n".join(P)


def _sec_photo(plan: dict) -> str:
    """美景拍摄指南: photo/extreme/nature 画像或用户提及拍照/星空/日出日落时渲染。"""
    style = plan.get("style", "")
    prefs_text = " ".join(str(p) for p in (plan.get("prefs") or []))
    blob = " ".join(plan.get("tone", [])) + prefs_text + " " + str(plan.get("composition", ""))
    wants_photo = any(w in blob for w in ("拍照", "出片", "摄影", "星空", "银河", "日出", "日落", "机位", "照片"))
    if style not in ("photo", "extreme", "nature") and not wants_photo:
        return ""
    data = load_json(PHOTO_DATA)
    P = [sec_open("photo", "📷", "美景拍摄指南", "机位 · 时机 · 参数一次讲清")]

    ss = data.get("sunrise_sunset", {})
    P.append(f"""<div class="card"><h3>{icon("🌅")} {esc(ss.get("label","日出日落"))}</h3>
  <table><tr><th style="width:40px">时机</th><td>{esc("；".join(ss.get("timing", [])[:4]))}</td></tr>
  <tr><th>机位</th><td>{esc("；".join(ss.get("spots", [])[:5]))}</td></tr>
  <tr><th>参数</th><td>{esc("；".join(ss.get("params", [])[:4]))}</td></tr></table></div>""")

    if any(w in blob for w in ("星空", "银河", "观星", "星轨")) or style in ("nature", "photo"):
        st = data.get("starry", {})
        P.append(f"""<div class="card"><h3>{icon("🌌")} {esc(st.get("label","星空"))}</h3>
  <table><tr><th style="width:40px">前提</th><td>{esc("；".join(st.get("preconditions", [])[:5]))}</td></tr>
  <tr><th>地点</th><td>{esc("；".join(st.get("locations", [])[:3]))}</td></tr>
  <tr><th>参数</th><td>{esc("；".join(st.get("params", [])[:6]))}</td></tr></table>
  {note("<b>夜间安全</b>：" + esc("；".join(st.get("safety", []))), "caution")}</div>""")

    sc = data.get("scenes", {})
    scene_cards = []
    for k, s in sc.get("scenes", {}).items():
        scene_cards.append(f'<div class="card"><h3>{icon("🖼")} {esc(s.get("label",""))}</h3>{ul(s.get("tips", [])[:4])}</div>')
    if scene_cards:
        P.append('<div class="grid2">' + "".join(scene_cards) + "</div>")

    g = data.get("gear", {})
    if g.get("items"):
        P.append(f'<div class="card"><h3>{icon("🎒")} {esc(g.get("label","拍摄装备"))}</h3>{ul(g["items"])}</div>')

    nr = data.get("nearby_rule", {})
    if nr.get("items"):
        P.append(note("<b>" + esc(nr.get("label", "")) + "</b>——" + esc("；".join(nr["items"][:4])), "tip"))
    return "\n".join(P)


def _sec_concert(plan: dict) -> str:
    """演唱会（锚点事件型旅程）板块: 演出时刻为锚, 到达时间决策树 + 住宿策略 + 观演贴士。"""
    c = plan.get("concert")
    if not c:
        return ""
    P = [sec_open("concert", "🎤", "演唱会之旅 · 锚点攻略",
                  f"演出时刻固定，行程围绕第 {c.get('show_day')} 天（演出日）拼装")]
    P.append(note("<b>核心原则</b>：" + esc(c.get("principle", "")), "tip"))

    ar = c.get("arrival_rule", {})
    branches = []
    for b in ar.get("branches", []):
        branches.append(f"""<div class="card"><h3 style="font-size:13.5px">{esc(b.get('when',''))}</h3>
  {tagify([b.get("strategy","")])}
  <div style="font-size:12.5px;margin-top:5px;color:var(--sub)">{esc(b.get("detail",""))}</div></div>""")
    if branches:
        P.append(f'<div class="card"><h3>{icon("🕐")} {esc(ar.get("label","到达时间决策树"))}</h3>'
                 f'<div class="grid2">{"".join(branches)}</div></div>')

    st = c.get("show_day_template", {})
    if st.get("timeline"):
        P.append(f'<div class="card"><h3>{icon("📋")} {esc(st.get("label","演出日节奏"))}</h3>{ul(st["timeline"])}</div>')

    ss = c.get("stay_strategy", {})
    if ss.get("rules"):
        P.append(f'<div class="card"><h3>{icon("🏨")} {esc(ss.get("label","住哪"))}</h3>{ul(ss["rules"])}</div>')

    lg = c.get("logistics", {})
    lg_cards = []
    for key, ico, name in (("entry", "🎫", "入场"), ("banned", "🚫", "禁带物品"), ("exit", "🚇", "散场交通")):
        if lg.get(key):
            lg_cards.append(f'<div class="card"><h3>{icon(ico)} {name}</h3>{ul(lg[key])}</div>')
    if lg_cards:
        P.append(f'<div class="card"><h3>{icon("🎤")} {esc(lg.get("label","观演贴士"))}</h3>'
                 f'<div class="grid2">{"".join(lg_cards)}</div></div>')

    dt = c.get("days_template", {})
    if dt.get("text"):
        P.append(note("<b>" + esc(dt.get("label", "天数模板")) + "</b>——" + esc(dt["text"]), "tip"))
    pe = c.get("packing_extra") or []
    if pe:
        P.append(f'<div class="card"><h3>{icon("🎒")} 观演专属装备</h3>{tagify(pe)}</div>')
    return "\n".join(P)


def _sec_prefs(plan: dict) -> str:
    prefs = plan.get("prefs") or []
    if not prefs:
        return ""
    items = []
    for p in prefs:
        if isinstance(p, dict):
            topic = p.get("主题") or p.get("title") or ""
            body = p.get("内容") or p.get("text") or ""
            items.append(f"<b>{esc(topic)}</b> — {esc(body)}" if topic else esc(body))
        else:
            items.append(esc(p))
    out = sec_open("prefs", "🎯", "出行偏好", "按你的诉求定制")
    return out + f'<div class="card">{ul(items)}</div>'


def _sec_cold(plan: dict) -> str:
    """冷知识：只渲染真实可信、且与目的地强相关的本地事实；不写套话, 没有就不出板块。"""
    cold = plan.get("cold") or []
    if isinstance(cold, dict):
        cold = [cold]
    facts = []
    for block in cold:
        if not isinstance(block, dict):
            continue
        for f in block.get("facts") or []:
            if isinstance(f, dict):
                facts.append(f"<b>{esc(f.get('标题',''))}</b> — {esc(f.get('内容',''))}")
            else:
                facts.append(esc(f))
    if not facts:
        return ""  # 没有可靠的本地冷知识就不占位置
    P = [sec_open("cold", "❄", "本地冷知识", "出发前多知道一点")]
    P.append(f'<div class="card"><h3>冷知识</h3>{ul(facts)}</div>')
    return "\n".join(P)


def _sec_audience(plan: dict) -> str:
    a = plan.get("audience") or {}
    if not isinstance(a, dict) or a.get("key") in ("general", None):
        return ""
    icons = {"male": "🧭", "female": "🌸", "family": "👨‍👩‍👧", "elderly": "🧓"}
    ico = icons.get(a.get("key"), "🎯")
    out = sec_open("audience", ico, f"受众专属准备 · {esc(a.get('label',''))}", "你不问，我们也准备好了")
    cards = []
    for title, key in (("关注重心", "focus"), ("偏好玩法", "like"), ("避坑", "avoid"), ("实操贴士", "tips")):
        v = a.get(key)
        if v:
            cards.append(f'<div class="card"><h3>{title}</h3>{ul(v if isinstance(v, list) else [v])}</div>')
    band_tips = a.get("band_tips") or []
    if a.get("band") and band_tips:
        cards.append(f'<div class="card"><h3>分龄要点 · {esc(a["band"])}</h3>{ul(band_tips if isinstance(band_tips, list) else [band_tips])}</div>')
    return out + '<div class="grid2">' + "".join(cards) + "</div>"


def _sec_context(ctx: dict | None) -> str:
    c = ctx or {}
    if not c:
        return ""
    P = [sec_open("context", "🌡", "出行须知", "季节适配与车辆规划")]
    if c.get("season_note"):
        P.append(f'<div class="card"><h3>当季要点</h3><div style="font-size:13px">{esc(c["season_note"])}</div></div>')
    cars = c.get("cars") or []
    if cars:
        rows = "".join(
            f"<tr><td><b>{esc(x.get('type',''))}</b></td><td>{esc(x.get('shortboard',''))}</td>"
            f"<td>{esc(x.get('strategy',''))}</td></tr>" for x in cars)
        P.append(f'<div class="card"><h3>{icon("🚗")} 动力类型差异</h3><table><tr><th>类型</th><th>短板</th><th>补能策略</th></tr>{rows}</table></div>')
    if c.get("holiday_note"):
        P.append(note(esc(c["holiday_note"]), "caution"))
    return "\n".join(P)


# ---------------------------------------------------------------- 主函数

def _collect_places(plan) -> set:
    places = set()
    if plan.get("origin"):
        places.add(plan["origin"])
    for d in (plan.get("destinations") or []):
        if isinstance(d, str):
            places.add(d)
        elif isinstance(d, dict):
            places.add(d.get("name") or d.get("city") or "")
    for day in (plan.get("plan") or []):
        c = day.get("city")
        if c:
            places.add(c)
    places.discard("")
    return places


def _resolve_gate_rules(place: str, rules: dict):
    dests = rules.get("destinations") or {}
    seen = set()
    cur = place
    while cur and cur not in seen:
        seen.add(cur)
        node = dests.get(cur)
        if node and "gates" in node:
            return node["gates"]
        if node and "alias_of" in node:
            cur = node["alias_of"]
            continue
        return None
    return None


def _plan_text(plan) -> str:
    parts = []
    for day in (plan.get("plan") or []):
        parts.append(day.get("city") or "")
        for s in (day.get("slots") or []):
            parts.append((s.get("label") or "") + " " + (s.get("desc") or ""))
        if day.get("note"):
            parts.append(day["note"])
    for k in ("tips", "safety"):
        v = plan.get(k)
        if isinstance(v, list):
            parts.append(" ".join(str(x) for x in v))
        elif isinstance(v, dict):
            parts.append(" ".join(str(x) for x in v.values()))
    t = plan.get("transit")
    if isinstance(t, dict):
        parts.append(" ".join(str(x) for x in t.values()))
    return "\n".join(parts)


def _time_near(text: str, keyword: str):
    import re
    idx = text.find(keyword)
    if idx < 0:
        return None
    seg = text[idx: idx + 40]
    m = re.search(r"(\d{1,2})[:：](\d{2})", seg)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def run_feasibility(plan: dict, rules: dict | None = None) -> dict:
    """零依赖可行性体检引擎：阈值自检 + 目的地 P0 关卡覆盖检测 + 末班船时间一致性断言。"""
    if rules is None:
        rules = load_feas_rules()
    threshold, p0, assert_issues = [], [], []
    days = plan.get("plan", []) or []
    tips = rules.get("tips", {})
    mpd = rules.get("max_spots_per_day", 6)
    late = rules.get("late_hour", 21)
    # ── 阈值自检（节奏/体力）──
    for day in days:
        dno = day.get("day", "?")
        try:
            spots = int(day.get("spots") or 0)
        except Exception:
            spots = 0
        if spots > mpd:
            threshold.append(f"D{dno} 排了 {spots} 个点位，超过单日建议上限 {mpd}——{tips.get('too_many_spots','')}")
        latest = 0
        for s in day.get("slots", []):
            hh = ""
            for ch in str(s.get("time", "") or ""):
                if ch.isdigit():
                    hh += ch
                else:
                    break
            if hh:
                try:
                    h = int(hh)
                    if h > latest:
                        latest = h
                except Exception:
                    pass
        if latest and latest > late:
            threshold.append(f"D{dno} 末段约 {latest}:00 仍安排在外，注意末班车与夜间安全——{tips.get('late_night','')}")
    if plan.get("high_altitude") and len(days) < rules.get("altitude_min_days", 3):
        threshold.append(tips.get("altitude", ""))
    if len(days) >= rules.get("long_trip_days", 7) and not any((day.get("label") or "").find("休") >= 0 for day in days):
        threshold.append(tips.get("long_trip", ""))
    for day in days:
        if day.get("transfer"):
            try:
                sp = int(day.get("spots") or 0)
            except Exception:
                sp = 0
            if sp > rules.get("transfer_max_spots", 3):
                threshold.append(f"D{day.get('day')} 为跨城转场日仍排 {sp} 个点位——{tips.get('tight_transfer','')}")
    # ── 目的地 P0 关卡覆盖检测 ──
    places = _collect_places(plan)
    origin = plan.get("origin")
    visited_origin = any((d.get("city") or "") == origin for d in days)
    if origin and not visited_origin:
        places.discard(origin)  # 纯出发地不触发景点类关卡
    text = _plan_text(plan)
    # 任何在行程文本中出现的已知目的地/景点关键词，也纳入关卡检测（spots 不以城市维度出现时也能抓到）
    for key in (rules.get("destinations") or {}):
        if key == origin:
            continue  # 出发地不在文本扫描里触发
        if key in text:
            places.add(key)
    kw = rules.get("gate_keywords", {})
    for place in sorted(places):
        gr = _resolve_gate_rules(place, rules)
        if not gr:
            continue
        for gtype, g in gr.items():
            covered = any(k in text for k in kw.get(gtype, []))
            if not covered:
                p0.append({"level": g.get("level", "P2"), "place": place,
                           "gate": gtype, "text": g.get("text", "")})
            asr = g.get("assert")
            if asr and asr.get("type") == "last_ferry":
                stated = _time_near(text, "末班")
                if stated and stated != asr["value"]:
                    assert_issues.append({
                        "level": "P0", "place": place,
                        "text": f"行程写「末班船 {stated}」与权威值「{asr['value']}」冲突——请复核真实末班时间，避免误船。"})
    return {"threshold": threshold, "p0": p0, "assert": assert_issues}


def _sec_feasibility(plan: dict, feas: dict | None = None) -> str:
    """可执行性体检：阈值自检 + 目的地 P0 关卡（零依赖，非实时）。"""
    rules = load_feas_rules()
    if feas is None:
        feas = run_feasibility(plan, rules)
    P = [sec_open("feasibility", "📋", "可执行性体检", "零依赖自检 · 含 P0 关卡")]
    if feas["threshold"]:
        P.append(f'<div class="card"><h3>节奏 / 体力阈值</h3>{ul(feas["threshold"])}</div>')
    if feas["p0"]:
        p0html = "".join(
            f'<li><span class="feat-badge {"warn" if i["level"]=="P0" else "tip"}">{i["level"]}</span>'
            f' <b>{esc(i["place"])}</b> · {esc(i["text"])}</li>' for i in feas["p0"])
        P.append(f'<div class="card"><h3>目的地强制关卡（未覆盖项）</h3>'
                 f'<p class="sub" style="margin:2px 0 8px;color:var(--sub)">'
                 f'以下 P0/P1/P2 关卡在行程中未出现对应安排，出行前请确认落实。</p>'
                 f'<ul class="kv">{p0html}</ul></div>')
    if feas["assert"]:
        ahtml = "".join(f'<li><span class="feat-badge warn">P0</span> {esc(i["text"])}</li>' for i in feas["assert"])
        P.append(f'<div class="card" style="border:1px solid var(--warn)"><h3>⚠ 数据一致性冲突</h3>'
                 f'<ul class="kv">{ahtml}</ul></div>')
    total_p0 = sum(1 for i in feas["p0"] if i["level"] == "P0") + len(feas["assert"])
    passed = (not feas["threshold"]) and (not feas["p0"]) and (not feas["assert"])
    badge = "ok" if passed else "warn"
    label = "可执行性良好" if passed else f"发现 {len(feas['threshold'])+len(feas['p0'])+len(feas['assert'])} 项需留意（含 {total_p0} 项 P0）"
    body = (note("各项指标基于经验阈值与本地关卡库（不含实时交通/票务/天气）。"
                 "P0 为出行前必须复核的硬项；出行前 1–3 天请以官方实时信息为准。", "caution")
            if not passed else
            note("各项指标均在经验安全阈值内，行程节奏与体力分配合理，可执行性良好。", "tip"))
    P.append(f'<div class="card"><h3>体检结论<span class="feat-badge {badge}">{label}</span></h3>{body}</div>')
    return "\n".join(P)


def feasibility_banner(feas: dict | None, mode: str) -> str:
    """册首门禁横幅：strict 红色强制 / advisory 黄色提示（零依赖下抓硬错）。"""
    if not feas:
        return ""
    p0_hard = [i for i in feas["p0"] if i["level"] == "P0"] + feas["assert"]
    p0_soft = [i for i in feas["p0"] if i["level"] == "P1"]
    if mode == "strict":
        if p0_hard:
            items = "".join(f"<li>{esc(i.get('text', i.get('place', '')))}</li>" for i in p0_hard)
            return (f'<div class="feas-gate gate-strict"><b>🛑 可行性体检未通过（强制关卡）</b>'
                    f'<p>本行程存在 {len(p0_hard)} 项 P0 硬错，出行前必须复核：</p><ul>{items}</ul></div>')
        if p0_soft:
            items = "".join(f"<li>{esc(i['text'])}</li>" for i in p0_soft)
            return (f'<div class="feas-gate gate-advisory"><b>⚠ 可行性体检提示</b>'
                    f'<p>无 P0 硬错；{len(p0_soft)} 项 P1 建议已列入「可执行性体检」板块。</p><ul>{items}</ul></div>')
        return '<div class="feas-gate gate-ok">✅ 可行性体检通过：未发现 P0 硬错（零依赖关卡库校验）。</div>'
    # advisory
    if p0_hard:
        items = "".join(f"<li>{esc(i.get('text', i.get('place', '')))}</li>" for i in p0_hard)
        return (f'<div class="feas-gate gate-advisory"><b>⚠ 可行性体检提示</b>'
                f'<p>发现 {len(p0_hard)} 项 P0 硬错建议关注（开启 --feasibility strict 可置顶强制）：</p><ul>{items}</ul></div>')
    if p0_soft:
        return (f'<div class="feas-gate gate-ok"><b>ℹ 可行性体检</b>'
                f'<p>{len(p0_soft)} 项 P1 建议已列入「可执行性体检」板块，出行前确认即可。</p></div>')
    return '<div class="feas-gate gate-ok">✅ 可行性体检无异常（零依赖关卡库校验）。</div>'


def _sec_rv(plan: dict) -> str:
    """房车 / 自驾后勤自检板块（v0.1.13）。

    只对含 rv 键的 plan 输出（rv 画像，或 roadtrip 画像且用户声明了车型）；
    其余行程 plan 里没有 rv 键，直接返回空串，不渲染。
    HTML 由 rv_check.rv_html 生成，与 gate_card / moto_card 共用视觉语言。
    """
    rb = plan.get("rv")
    if not rb or not _RV_AVAILABLE or not rv_html:
        return ""
    try:
        return rv_html(rb, " · ".join(plan.get("destinations") or []))
    except Exception:
        return ""


def _sec_moto(plan: dict) -> str:
    """摩旅可行性自检 + 待核实清单 + 参考线路板块（v0.1.1 起，v0.1.2 扩充）。

    只对 moto 画像输出 —— 非摩旅行程的 plan 里没有 moto 键，直接返回空串。
    板块 HTML 由 moto_check.moto_html 生成，与 gate_card 共用视觉语言与排版规范；
    v0.1.2 起追加 moto_enrich.enrichment_html（出行前待核实清单 + 已落地笔记）。
    """
    mb = plan.get("moto")
    if not mb or not _MOTO_AVAILABLE or not moto_html:
        return ""
    try:
        html = moto_html(mb, " · ".join(plan.get("destinations") or []))
    except Exception:
        return ""
    # v0.1.2：出行前待核实清单（数据增强通道）
    en = (mb.get("enrichment") or {})
    cl = en.get("checklist") or {}
    if cl and _MOTO_ENRICH_AVAILABLE and enrichment_html:
        try:
            html += enrichment_html(cl, en.get("notes"))
        except Exception:
            pass
    # v0.1.2：参考线路带绿荫等级与夏季窗口
    rts = mb.get("routes") or []
    if rts:
        items = ""
        for r in rts:
            shade = (r.get("shade") or "").strip()
            shade_badge = ""
            if shade:
                c = {"高": "#639922", "中": "#BA7517", "低": "#A32D2D"}.get(shade, "#666")
                shade_badge = (f'<span class="feat-badge" style="background:{c}22;color:{c};'
                               f'border:1px solid {c}">绿荫 {shade}</span>')
            summer = (r.get("summer_window") or "").strip()
            est = "（估）" if (r.get("distance_source") or "") == "editorial_estimate" else ""
            items += (
                f'<li style="margin:0 0 10px"><b>{esc(r.get("name") or "")}</b> {shade_badge}'
                f'<span class="feat-badge">{esc(r.get("group_label") or "")}</span>'
                f'<span class="feat-badge">{esc(r.get("km"))}km{est}</span>'
                f'<span class="feat-badge">{esc(r.get("days"))} 天</span>'
                f'<span class="feat-badge">难度 {esc(r.get("level"))}/5</span>'
                f'<div style="font-size:12.5px;line-height:1.6;color:var(--sub);margin-top:3px">'
                f'{esc(r.get("highlight") or "")}</div>'
                + (f'<div style="font-size:12.5px;line-height:1.6;margin-top:2px">'
                   f'暴晒与时段：{esc(summer)}</div>' if summer else "")
                + (f'<div style="font-size:12.5px;line-height:1.6;margin-top:2px">'
                   f'绿荫依据：{esc(r.get("shade_note") or "")}</div>' if r.get("shade_note") else "")
                + f'<div style="font-size:12.5px;line-height:1.6;margin-top:2px">'
                  f'⚠ {esc(r.get("caution") or "")}</div></li>')
        html += (f'<div class="card"><h3>参考线路'
                 f'<span class="feat-badge">{len(rts)} 条</span></h3>'
                 f'<p style="font-size:12.5px;line-height:1.65;color:var(--sub);margin:0 0 8px">'
                 f'线路为稳定事实（走向、地形、季节规律），非实时路况；'
                 f'绿荫等级基于地形性质定性判断，出行前按上方清单逐项核实。</p>'
                 f'<ul class="kv">{items}</ul></div>')
    return html


def render(plan: dict, research: dict | None, weather: dict | None,
           poi: dict | None, context: dict | None, transit: dict | None,
           out_path: str, title: str | None) -> None:
    global _IMAGES, MAP_MODE, FEAS_RESULT, GATE_RESULT, CRED_RESULT
    _IMAGES = plan.get("images") or {}
    # ── 风格解析：手动覆盖优先，否则按行程类型自动选风 ──
    apply_style(FORCED_STYLE, plan)
    # ── 可行性体检：零依赖关卡，advisory/strict 时计算并置顶门禁 ──
    if FEAS_MODE != "none":
        FEAS_RESULT = run_feasibility(plan)
    else:
        FEAS_RESULT = None

    # ── v0.2.0 出境 4 维约束（准入 / 货币 / 合规文化 / 领事安全）──
    # 国界改变的是约束不是求解器：排程/比选/预算/体检/渲染 0 改动复用。
    # 必须在门禁卡之前算好——门禁的准入维度直接取自 OC.admission()。
    OC = None
    if _GATE_AVAILABLE:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from outbound_constraints import OutboundConstraints
            _oc_probe = OutboundConstraints(plan.get("destinations") or [])
            if _oc_probe.outbound:
                OC = _oc_probe
                plan.setdefault("credibility", [])
                plan["credibility"].extend(OC.all_facts())
        except Exception as e:
            print(f"⚠️ 出境约束未启用（{e}）；继续以国内流程渲染。")
            OC = None

    # ── v0.2.0 可行性门禁卡：先判「能不能成」，再谈「怎么玩」 ──
    # gate 优先级：plan 显式 gate > 出境约束自动推导的准入维度
    gate_input = plan.get("gate") if isinstance(plan.get("gate"), dict) else None
    if not gate_input and OC is not None:
        try:
            gate_input = OC.admission(
                passport_valid_months=(plan.get("passport") or {}).get("valid_months"),
                days_to_depart=(plan.get("trip") or {}).get("days_to_depart"),
                insurance_amount=(plan.get("insurance") or {}).get("amount"))
        except Exception:
            gate_input = None
    GATE_RESULT = None
    if _GATE_AVAILABLE and GATE_MODE != "none" and gate_input:
        GATE_RESULT = gate_card(gate_input)
        dest_txt = " · ".join(plan.get("destinations") or []) or (plan.get("origin") or "目的地")
        # 红灯 + strict = 硬拦停：只输出拦停页，不渲染行程正文
        if GATE_RESULT["blocked"] and GATE_MODE == "strict":
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(blocked_page(GATE_RESULT, dest_txt))
            print(f"⛔ 门禁未通过（{GATE_RESULT['red']} 项红灯），已输出拦停页：{out_path}")
            print("   红灯未清空前不渲染行程正文——先解决准入，再谈行程。")
            return

    # ── v0.2.0 可信度内核：易变信息未核验则挂降级角标，摊开台账 ──
    CRED_RESULT = None
    if _GATE_AVAILABLE:
        try:
            cred = Credibility()
            for fact in (plan.get("credibility") or []):
                cred.declare(fact.get("key", fact.get("label", "")),
                             fact.get("label", ""), fact.get("value"),
                             domain=fact.get("domain"), level=fact.get("level"),
                             official_hint=fact.get("official_hint", ""))
                if fact.get("verified_source"):
                    cred.mark_verified(fact.get("key", fact.get("label", "")),
                                       fact["verified_source"], fact.get("verified_on"))
            CRED_RESULT = cred if cred.stats()["total"] else None
        except Exception:
            CRED_RESULT = None

    parts = [
        gate_html(GATE_RESULT) if GATE_RESULT else "",
        _sec_moto(plan),
        _sec_rv(plan),
        _sec_overview(plan), _sec_season(plan), _sec_route(plan),
        _sec_outbound(plan, OC),
        _sec_feasibility(plan, FEAS_RESULT), _sec_transit(plan, transit), _sec_carbon(plan, transit), _sec_research(plan, research),
        _sec_ugc(research), _sec_pitfall(research),
        _sec_weather(weather), _sec_weather_contingency(weather),         _sec_poi(plan, poi or {}), _sec_context(context),
        _sec_photo(plan), _sec_concert(plan),
        _sec_stay(plan), _sec_budget(plan), _sec_extreme_nature(plan), _sec_packing(plan),
        _sec_safety(plan), _sec_altitude(plan), _sec_prefs(plan), _sec_cold(plan), _sec_audience(plan),
        (CRED_RESULT.section_html() if CRED_RESULT else ""),
        _sec_image_credits(plan),
    ]

    body = "\n".join(p for p in parts if p)
    toc = build_toc()
    dest = " · ".join(plan.get("destinations") or [])
    h1 = title or f"{dest}{plan.get('days')}日 · {plan.get('style_label','')}小册子"
    frm = plan.get("origin")
    kicker = f"从{frm}出发" if frm else "AI 旅行指南小册子"
    feas_banner = feasibility_banner(FEAS_RESULT, FEAS_MODE) if FEAS_MODE != "none" else ""

    cover_url = plan.get("cover_url")
    cover_credit = plan.get("cover_credit") or {}
    if cover_url:
        cap = cover_credit.get("title") or "南岳衡山实景"
        cover_html = (
            f'<img class="cover" src="{esc(cover_url)}" alt="{esc(dest)}" '
            f'onerror="this.style.display=\'none\';if(this.nextElementSibling)this.nextElementSibling.style.display=\'none\'">'
            f'<div class="cover-cap">📷 {esc(cap)} · 来源 Wikimedia Commons（自由授权）</div>')
    else:
        # v0.1.0 修正：无封面图时【不渲染任何占位框】，杜绝空白占位与标题被挤压
        cover_html = ""

    trip_json = json.dumps(plan, ensure_ascii=False).replace("</", "<\\/")
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(h1)}</title>
<style>{CSS}
{STYLE_OVERRIDE}</style>
</head>
<body>
{toc}
<div class="wrap">
  {feas_banner}
  <div class="hero">
    <div class="hero-kicker">{esc(kicker)}</div>
    <h1>{esc(h1)}</h1>
    <p>本小册子由 AI 行程引擎编排：节奏配平、季节方案、交通比选、行前清单与安全提醒一次性备齐。
    票价与开放时间以官方渠道实时为准。</p>
    <div class="brandline">AI 旅行指南小册子 · 由 Agent 生成</div>
  </div>
  {cover_html}
  {body}
  <footer>AI 旅行指南小册子 — 由 Agent 生成 · 天气为预报值 · 门票/班次以官方为准 · 户外活动请量力而行</footer>
</div>
<div class="fab-stack">
  <button class="fab" onclick="savePDF()" title="保存为 PDF">📄<span class="tip-txt">保存为 PDF</span></button>
  <button class="fab" onclick="exportICS()" title="导出日历 .ics">📅<span class="tip-txt">导出日历 .ics</span></button>
  <button class="fab" onclick="copyItinerary()" title="复制行程">📋<span class="tip-txt">复制行程</span></button>
  <button class="fab" onclick="scrollTop()" title="回到顶部">⬆️<span class="tip-txt">回到顶部</span></button>
</div>
<div class="toast" id="tg-toast"></div>
<script id="trip-data" type="application/json">{trip_json}</script>
<script>{JS}</script>
</body>
</html>"""
    Path(out_path).write_text(doc, encoding="utf-8")
    print(f"✅ 已生成: {out_path}  (板块 {len(_registry)} 个)")


def main() -> int:
    ap = argparse.ArgumentParser(description="苹果风旅行小册子渲染器")
    ap.add_argument("--plan", required=True, help="行程 JSON (build_itinerary.py 产物)")
    ap.add_argument("--research", help="调研素材 JSON")
    ap.add_argument("--weather", help="天气预检 JSON")
    ap.add_argument("--poi", help="景点票务 JSON")
    ap.add_argument("--context", help="季节/车辆 JSON")
    ap.add_argument("--transit", help="交通比选 JSON")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument("--title", help="报告标题")
    ap.add_argument("--variant", choices=["full", "light"], default="full",
                    help="light=紧凑版（精简逐日描述与可选可视化）")
    ap.add_argument("--format", choices=["html", "md"], default="html",
                    help="输出格式：html 或 Markdown")
    ap.add_argument("--style", choices=list(STYLES.keys()), default=None,
                    help="报告视觉风格（默认按行程类型自动选风）")
    ap.add_argument("--map", choices=["none", "offline"], default="none",
                    help="路线地图层：none=零依赖不画；offline=SVG 离线手绘示意（不调用在线地图）")
    ap.add_argument("--compute", choices=["none", "map", "12306"], default="none",
                    help="实算插件：map=地图服务距离/路径；12306=票价。需配置环境变量，否则回落估算")
    ap.add_argument("--feasibility", choices=["none", "advisory", "strict"], default="advisory",
                    help="可行性体检门禁：none=关闭；advisory=册首提示+板块(默认)；strict=置顶红色强制关卡")
    ap.add_argument("--no-images", action="store_true",
                    help="强制纯文字渲染：忽略 plan 中的 cover_url / images / cover_credit，不输出任何图片与授权区块。用于「用户版」默认精简出册。")
    ap.add_argument("--gate", choices=["auto", "none", "advisory", "strict"], default="auto",
                    help="出境可行性门禁卡：auto=plan 含 gate 时启用(默认)；none=关闭；"
                         "advisory=四灯置顶展示；strict=红灯直接拦停不输出行程正文")
    args = ap.parse_args()

    global COMPACT, FORCED_STYLE, MAP_MODE, COMPUTE_MODE, FEAS_MODE, GATE_MODE
    COMPACT = (args.variant == "light")
    FORCED_STYLE = args.style
    MAP_MODE = args.map
    COMPUTE_MODE = args.compute
    FEAS_MODE = args.feasibility
    GATE_MODE = args.gate

    plan = json.load(open(args.plan, encoding="utf-8"))
    research = json.load(open(args.research, encoding="utf-8")) if args.research else None
    weather = json.load(open(args.weather, encoding="utf-8")) if args.weather else None
    poi = json.load(open(args.poi, encoding="utf-8")) if args.poi else {}
    context = json.load(open(args.context, encoding="utf-8")) if args.context else None
    transit = json.load(open(args.transit, encoding="utf-8")) if args.transit else None
    # v0.1.0：允许把 research/weather/context/poi 内嵌进 plan，单一文件即可驱动全册（更稳健）
    research = research or plan.get("research")
    weather = weather or plan.get("weather")
    context = context or plan.get("context")
    poi = poi or plan.get("poi") or {}

    # ── v0.1.0：默认不接图源（用户版精简）。--no-images 显式压掉一切图片；
    #    即便 plan 中带了 cover_url / images，也会被清空，保证纯文字出册。 ──
    if args.no_images:
        plan["cover_url"] = None
        plan["images"] = {}
        plan["cover_credit"] = {}
        print("🖼 已按 --no-images 强制纯文字渲染（忽略所有图片字段）。")

    # ── 可选实算插件（v0.0.9）：配置环境变量后注入真实里程/票价，否则回落估算 ──
    if COMPUTE_MODE != "none" and transit:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import compute_plugin as cp
            transit, _ = cp.enrich_transit(transit, _load_coords(), COMPUTE_MODE)
        except Exception as e:
            print(f"⚠️ 实算插件未启用（{e}）；继续以估算值渲染。")

    if args.format == "md":
        render_markdown(plan, research, weather, poi, context, transit, args.out, args.title)
    else:
        render(plan, research, weather, poi, context, transit, args.out, args.title)
    # 提示本次实际生效的风格与地图模式
    print(f"🎨 风格：{STYLES[CUR_STYLE]['label']}（{CUR_STYLE}）　🗺 地图：{MAP_MODE}　📋 体检：{FEAS_MODE}")
    return 0


# ---------------------------------------------------------------- Markdown 导出（轻量多形态交付）
def _md_esc(s) -> str:
    return str(s).replace("\n", " ").strip()


def render_markdown(plan, research, weather, poi, context, transit, out_path, title=None) -> None:
    """输出纯文本 Markdown 小册子：便于贴入便签 / 即时通讯 / 文档，零样式依赖。"""
    L = []
    dest = " · ".join(plan.get("destinations") or [])
    h1 = title or f"{dest}{plan.get('days')}日 · {plan.get('style_label','')}小册子"
    L.append(f"# {h1}\n")
    L.append(f"> 从{plan.get('origin','')}出发 · {plan.get('people')}人 · {plan.get('days')}天 · "
             f"节奏「{plan.get('style_label','')}」\n")

    b = plan.get("budget") or {}
    L.append("## 行程概览\n")
    L.append(f"- 目的地：{dest}")
    L.append(f"- 人均预算(估)：¥{b.get('per_person_total','—')}　全团合计(估)：¥{b.get('group_total','—')}")
    tone = plan.get("tone") or []
    if tone:
        L.append(f"- 节奏关键词：{'、'.join(tone)}")
    L.append("")

    L.append("## 逐日动线\n")
    for day in plan.get("plan", []):
        L.append(f"### Day {day.get('day')} · {_md_esc(day.get('label',''))}（{_md_esc(day.get('city',''))}）")
        for s in day.get("slots", []):
            desc = s.get("desc") or s.get("note") or ""
            L.append(f"- **{_md_esc(s.get('time',''))}** {_md_esc(s.get('label',''))}"
                     + (f"：{_md_esc(desc)}" if desc else ""))
        if day.get("note"):
            L.append(f"  - 备注：{_md_esc(day['note'])}")
        L.append("")

    if transit:
        L.append("## 交通方案比选\n")
        L.append(f"- 直线距离约 {transit.get('distance_km','—')} km")
        if transit.get("recommend"):
            L.append(f"- 推荐：**{_md_esc(transit['recommend'])}** —— {_md_esc(transit.get('reason',''))}")
        L.append("")

    if b.get("group"):
        L.append("## 预算安排（估算）\n")
        L.append("| 分项 | 全团(最低) | 人均(常规) |")
        L.append("| --- | --- | --- |")
        for k, v in b["group"].items():
            L.append(f"| {k} | ¥{v} | ¥{(b.get('per_person') or {}).get(k,0)} |")
        L.append(f"| **合计** | **¥{b.get('group_total')}** | **¥{b.get('per_person_total')}** |")
        L.append("")

    if plan.get("safety_scenes") or True:
        L.append("## 安全提醒\n")
        L.append("- 通用：保管好证件与财物，随身携带常用药品，保存当地紧急电话。")
        L.append("- 出行前查好天气与交通，夜间尽量结伴，量力而行。")
        L.append("")

    cold = plan.get("cold") or []
    if isinstance(cold, dict):
        cold = [cold]
    facts = []
    for blk in cold:
        if isinstance(blk, dict):
            for f in blk.get("facts") or []:
                facts.append(f.get("内容") or f if isinstance(f, dict) else f)
    if facts:
        L.append("## 本地冷知识\n")
        for f in facts:
            L.append(f"- {_md_esc(f)}")
        L.append("")

    L.append("---\n*AI 旅行指南小册子 · 由 Agent 生成 · 票价/开放时间以官方为准*")
    Path(out_path).write_text("\n".join(L), encoding="utf-8")
    print(f"✅ 已生成 Markdown: {out_path}")


if __name__ == "__main__":
    import sys
    sys.exit(main())
