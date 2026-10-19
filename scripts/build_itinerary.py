#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行程编排引擎: 把「几天 + 主题 + 预算」翻译成逐日动线与资源分配。

用法:
  python build_itinerary.py --to 成都 --days 3 --style leisure
  python build_itinerary.py --from 上海 --to 丽江大理 --days 7 --style roadtrip
  python build_itinerary.py --to 莫干山 --days 2 --style family --budget 3000

## 核心设计: 节奏引擎
不同旅行方式的差别不在景点,而在「每天塞几个点」和「留多少空白」。
本脚本用 STYLE_PROFILES 定义 21 种节奏画像(11 种基础 + 10 种扩展的国内全场景方式), 每个画像规定:
  - 每日景点数(密度)
  - 上午/下午/晚间的时段切分方式
  - 单点平均停留时长
  - 每日总活动时长(含休息)
  - 预算分配权重(交通/住宿/餐饮/门票/其他)
  - 物料清单(按出行方式)
  - 文案语气标记(交给 HTML 层渲染成不同口吻)

这样「特种兵密一点、休闲疏一点、度假轻快、蜜月开心、自驾看美景」不是
空话, 而是可计算的参数差异。
"""
import argparse
import json
import math
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import refloader

DATA = Path(__file__).resolve().parent.parent / "references" / "destinations.json"
RESTRICTIONS = Path(__file__).resolve().parent.parent / "references" / "restrictions.json"
COLD = Path(__file__).resolve().parent.parent / "references" / "cold_knowledge.json"
AUDIENCE = Path(__file__).resolve().parent.parent / "references" / "audience_profiles.json"
PARTY = Path(__file__).resolve().parent.parent / "references" / "party_playbooks.json"

# ── v0.1.1 摩旅模式：摩旅校验引擎（单独 try，缺失只关摩旅，不连带关掉其它能力）──
# 教训来自 render_booklet：曾把 credibility 与 gate_card 放同一个 try，
# 结果 gate_card 一缺失，可信度内核被静默关闭。这里必须独立导入。
try:
    from moto_check import moto_card, suggest_routes as moto_suggest_routes
    _MOTO_AVAILABLE = True
except Exception:  # pragma: no cover
    moto_card = None                     # type: ignore[assignment]
    moto_suggest_routes = None           # type: ignore[assignment]
    _MOTO_AVAILABLE = False

# ── v0.1.2 摩旅数据增强通道（同样独立 try，缺失只关增强，不关门禁自检）──
try:
    from moto_enrich import build_checklist as moto_build_checklist
    from moto_enrich import validate_notes as moto_validate_notes
    _MOTO_ENRICH_AVAILABLE = True
except Exception:  # pragma: no cover
    moto_build_checklist = None          # type: ignore[assignment]
    moto_validate_notes = None           # type: ignore[assignment]
    _MOTO_ENRICH_AVAILABLE = False

# ── v0.1.13 房车/自驾后勤自检（独立 try，缺失只关后勤卡，不拖累其余板块）──
try:
    from rv_check import rv_card
    _RV_AVAILABLE = True
except Exception:  # pragma: no cover
    rv_card = None                       # type: ignore[assignment]
    _RV_AVAILABLE = False

# 绿荫等级 → 排序权重（与 moto_check._SHADE_RANK 保持一致）
_SHADE_FLOOR = {"高": 3, "中": 2, "低": 1}


def moto_suggest_routes_shade_rank(r: dict) -> int:
    return _SHADE_FLOOR.get(r.get("shade") or "", 0)


def load_restrictions() -> dict:
    """读取常见限行/限高/禁摩规则(经验参考, 非实时)。"""
    try:
        with open(RESTRICTIONS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_cold() -> dict:
    """读取冷知识与趣味建议(经验科普, 非实时)。按目的地键存, 含通用交通。"""
    try:
        with open(COLD, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_audience() -> dict:
    """读取受众画像(男性/女性/家庭/老人/通用), 用于主动准备而非被动问答。"""
    try:
        with open(AUDIENCE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_party() -> dict:
    """读取出行陪伴结构（Party Type）玩法库。与 audience/style/theme 正交。"""
    try:
        with open(PARTY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 陪伴结构关键词（与 party_playbooks.json 一致；优先级 group→family→couple→friends→solo）
_GROUP_KW = ("团建", "研学", "夕阳红", "俱乐部", "团队", "旅行团", "公司", "工会", "协会",
             "定制团", "拓展", "会务", "包团", "组织者", "领队")
_FAMILY_KW = ("带娃", "带孩子", "亲子", "一家三口", "一家四口", "二大一小", "一大一小",
              "带父母", "带爸妈", "长辈", "老人", "全家", "家庭游", "家庭")
_COUPLE_KW = ("情侣", "夫妻", "蜜月", "新婚", "对象", "未婚夫", "未婚妻", "男友情", "女友情")
_FRIENDS_KW = ("闺蜜", "姐妹", "兄弟", "哥们", "同学", "朋友", "结伴", "宿舍", "搭子", "一群", "驴友", "球友")


def resolve_party_type(people: int, composition: str, hints=None, override: str = "") -> str:
    """判定出行陪伴结构（party type）。override 非空则直接采用（编排层显式指定）。
    优先级：group(有组织方) > family(跨代亲属/带娃老人) > couple(2人亲密) >
    friends-large(≥5)/friends-small(2-4) > solo(=1)。跨代亲属或组织方优先于纯朋友计数。"""
    if override:
        return override
    text = (composition or "") + " " + " ".join(hints or [])
    if any(k in text for k in _GROUP_KW):
        return "group"
    if any(k in text for k in _FAMILY_KW):
        return "family"
    if any(k in text for k in _COUPLE_KW) and people <= 2:
        return "couple"
    if people <= 1:
        return "solo"
    if any(k in text for k in _FRIENDS_KW) or people >= 2:
        return "friends-large" if people >= 5 else "friends-small"
    return "friends-small" if people >= 2 else "solo"


def party_block(party_db: dict, ptype: str, people: int, inferred: bool) -> dict:
    """从玩法库组装报告用的 party 块（缺该 type 数据则降级为占位，不抛错）。"""
    pt = (party_db.get("party_types") or {}).get(ptype, {})
    return {
        "type": ptype,
        "label": pt.get("label", ptype),
        "inferred": inferred,
        "room_note": pt.get("room_default", ""),
        "budget_mode": pt.get("budget_mode", ""),
        "budget_note": pt.get("budget_note", ""),
        "safety_focus": pt.get("safety_focus", []),
        "pacing_focus": pt.get("pacing_focus", []),
        "pitfalls": pt.get("pitfalls", ""),
        "people": people,
    }


def infer_audience(args) -> str:
    """从人员构成/原话片段/风格推断受众, 用户不提也先准备好。"""
    text = " ".join([
        (args.composition or ""),
        " ".join(args.hint or []),
        (args.style or ""),
    ])
    if any(k in text for k in ("老人", "父母", "长辈", "爷", "奶", "爸", "妈", "高龄")):
        return "elderly"
    if any(k in text for k in ("娃", "孩子", "宝宝", "宝", "亲子", "儿", "小学生", "青少年",
                                "3岁", "5岁", "6岁", "岁宝宝", "带小", "一小", "三口", "遛娃", "带娃", "孩")):
        return "family"
    if any(k in text for k in ("闺蜜", "女友", "姐妹", "妈妈团", "女生", "姐妹淘", "她")):
        return "female"
    if any(k in text for k in ("兄弟", "哥们", "男友", "男生", "老爷们", "他")):
        return "male"
    return "general"


def resolve_family_band(composition: str) -> str:
    """家庭出行时, 按人员构成关键词挑一个最贴切的年龄段建议。"""
    t = composition or ""
    if any(k in t for k in ("宝", "婴", "0-3", "一两岁", "1岁", "2岁", "3岁")):
        return "0-3"
    if any(k in t for k in ("3-6", "三四岁", "四五岁", "五六岁", "幼儿园")):
        return "3-6"
    if any(k in t for k in ("6-9", "小学生", "一二年级", "三四年级")):
        return "6-9"
    if any(k in t for k in ("10-15", "初中", "高中", "青少年", "十几岁")):
        return "10-15"
    return "3-6"  # 家庭默认给低龄稳妥建议


@dataclass
class StyleProfile:
    """一种旅行节奏画像。"""
    key: str
    label: str              # 中文名
    spots_per_day: tuple     # (最少, 最多) 每日景点数
    slot_hours: tuple        # 上午/下午/晚上 各时段时长(h)
    stay_per_spot_h: float   # 单点停留
    day_span_h: tuple        # 每日活动总时长区间
    budget_ratio: dict       # 预算分配权重
    tone: list               # 文案语气关键词(HTML 层用)
    gear_focus: list         # 重点物料方向
    intensity: int           # 强度 1-5, 用于排序与提示


# 21 种旅行画像(11 种基础 + 10 种扩展的国内全场景方式)
STYLE_PROFILES = {
    "commando": StyleProfile(
        key="commando", label="特种兵", spots_per_day=(6, 9),
        slot_hours=(4, 3, 2.5), stay_per_spot_h=1.0, day_span_h=(13, 16),
        budget_ratio={"交通": 0.30, "住宿": 0.25, "餐饮": 0.22, "门票": 0.13, "其他": 0.10},
        tone=["密集", "早出晚归", "一天顶三天", "走断腿", "特种兵"],
        gear_focus=["轻量化", "速干", "充电宝", "水壶"],
        intensity=5,
    ),
    "leisure": StyleProfile(
        key="leisure", label="休闲", spots_per_day=(3, 4),
        slot_hours=(3, 2.5, 2), stay_per_spot_h=1.8, day_span_h=(8, 10),
        budget_ratio={"交通": 0.22, "住宿": 0.33, "餐饮": 0.25, "门票": 0.10, "其他": 0.10},
        tone=["从容", "慢悠悠", "留白", "不赶", "坐下来"],
        gear_focus=["舒适", "折叠", "保温杯"],
        intensity=2,
    ),
    "resort": StyleProfile(
        key="resort", label="度假", spots_per_day=(1, 2),
        slot_hours=(2, 2, 2), stay_per_spot_h=3.0, day_span_h=(6, 8),
        budget_ratio={"交通": 0.20, "住宿": 0.42, "餐饮": 0.22, "门票": 0.05, "其他": 0.11},
        tone=["轻快", "发呆", "放空", "不设闹钟", "躺平"],
        gear_focus=["泳衣", "防晒", "浴巾", "遮阳帽"],
        intensity=1,
    ),
    "relax": StyleProfile(
        key="relax", label="散心", spots_per_day=(1, 1),
        slot_hours=(2, 2), stay_per_spot_h=4.0, day_span_h=(5, 7),
        budget_ratio={"交通": 0.15, "住宿": 0.45, "餐饮": 0.25, "门票": 0.03, "其他": 0.12},
        tone=["治愈", "放空", "慢", "不赶路", "对自己好一点"],
        gear_focus=["书", "耳机", "舒适鞋", "保温杯"],
        intensity=1,
    ),
    "honeymoon": StyleProfile(
        key="honeymoon", label="度蜜月", spots_per_day=(2, 3),
        slot_hours=(3, 3, 2.5), stay_per_spot_h=2.2, day_span_h=(8, 11),
        budget_ratio={"交通": 0.22, "住宿": 0.36, "餐饮": 0.24, "门票": 0.06, "其他": 0.12},
        tone=["开心", "浪漫", "纪念", "二人", "仪式感", "日出日落"],
        gear_focus=["正装", "拍立得", "氛围感", "红酒"],
        intensity=2,
    ),
    "roadtrip": StyleProfile(
        key="roadtrip", label="自驾", spots_per_day=(4, 6),
        slot_hours=(4, 3, 2), stay_per_spot_h=1.5, day_span_h=(11, 14),
        budget_ratio={"交通": 0.34, "住宿": 0.26, "餐饮": 0.20, "门票": 0.10, "其他": 0.10},
        tone=["美景", "沿途", "风景", "服务区", "车窗", "公路"],
        gear_focus=["行车记录仪", "充气泵", "拖车绳", "急救包", "保温杯", "零食"],
        intensity=4,
    ),
    "cycling": StyleProfile(
        key="cycling", label="骑行", spots_per_day=(2, 3),
        slot_hours=(4, 3, 1.5), stay_per_spot_h=1.5, day_span_h=(9, 12),
        budget_ratio={"交通": 0.18, "住宿": 0.30, "餐饮": 0.24, "门票": 0.06, "其他": 0.22},
        tone=["骑行", "码表", "爬坡", "补给点", "头盔", "日均里程"],
        gear_focus=["头盔", "骑行服", "码表", "补胎工具", "骑行手套", "反光条", "水壶"],
        intensity=4,
    ),
    "hiking": StyleProfile(
        key="hiking", label="徒步", spots_per_day=(1, 2),
        slot_hours=(5, 3, 1), stay_per_spot_h=3.5, day_span_h=(9, 12),
        budget_ratio={"交通": 0.22, "住宿": 0.28, "餐饮": 0.24, "门票": 0.08, "其他": 0.18},
        tone=["徒步", "海拔", "强度", "补给", "路况", "日出"],
        gear_focus=["登山杖", "徒步鞋", "速干", "护膝", "头灯", "雨衣", "GPS", "能量胶"],
        intensity=5,
    ),
    "moto": StyleProfile(
        key="moto", label="摩旅", spots_per_day=(3, 5),
        slot_hours=(4, 3, 2), stay_per_spot_h=1.5, day_span_h=(10, 14),
        budget_ratio={"交通": 0.32, "住宿": 0.28, "餐饮": 0.20, "门票": 0.05, "其他": 0.15},
        tone=["摩旅", "国道", "加油站", "驿站", "弯道", "里程"],
        gear_focus=["头盔", "骑行服", "护膝", "防风衣", "手套", "工具包", "拖车带", "补胎"],
        intensity=5,
    ),
    "family": StyleProfile(
        key="family", label="家庭亲子", spots_per_day=(3, 4),
        slot_hours=(3, 3, 2), stay_per_spot_h=2.0, day_span_h=(8, 11),
        budget_ratio={"交通": 0.24, "住宿": 0.32, "餐饮": 0.22, "门票": 0.12, "其他": 0.10},
        tone=["带娃", "亲子", "不累", "午睡", "安全", "寓教于乐"],
        gear_focus=["儿童雨衣", "零食", "湿巾", "常用药", "推车", "保温壶"],
        intensity=2,
    ),
    "couple": StyleProfile(
        key="couple", label="情侣", spots_per_day=(3, 4),
        slot_hours=(3.5, 3, 2.5), stay_per_spot_h=1.8, day_span_h=(9, 12),
        budget_ratio={"交通": 0.24, "住宿": 0.32, "餐饮": 0.24, "门票": 0.08, "其他": 0.12},
        tone=["约会", "氛围", "看日落", "二人", "出片"],
        gear_focus=["氛围穿搭", "相机", "野餐垫", "防晒"],
        intensity=3,
    ),
    "friends": StyleProfile(
        key="friends", label="朋友", spots_per_day=(4, 5),
        slot_hours=(4, 3, 3), stay_per_spot_h=1.5, day_span_h=(11, 14),
        budget_ratio={"交通": 0.28, "住宿": 0.26, "餐饮": 0.26, "门票": 0.10, "其他": 0.10},
        tone=["热闹", "整活", "拼", "夜宵", "拍照", "局"],
        gear_focus=["聚会", "零食", "酒", "音响", "充电宝"],
        intensity=4,
    ),
    # ── 扩展方式: 国内全场景覆盖 ──
    "camping": StyleProfile(
        key="camping", label="露营", spots_per_day=(1, 2),
        slot_hours=(3, 3, 2.5), stay_per_spot_h=3.0, day_span_h=(7, 10),
        budget_ratio={"交通": 0.18, "住宿": 0.10, "餐饮": 0.22, "门票": 0.05, "其他": 0.45},
        tone=["露营", "营地", "帐篷", "篝火", "星空", "自然"],
        gear_focus=["帐篷", "天幕", "睡袋", "防潮垫", "便携炉", "头灯", "折叠椅", "驱蚊"],
        intensity=2,
    ),
    "rv": StyleProfile(
        key="rv", label="房车", spots_per_day=(2, 3),
        slot_hours=(3.5, 3, 2.5), stay_per_spot_h=2.5, day_span_h=(8, 11),
        budget_ratio={"交通": 0.30, "住宿": 0.08, "餐饮": 0.24, "门票": 0.06, "其他": 0.32},
        tone=["房车", "营地", "驻车", "慢行", "车窗风景", "补给"],
        gear_focus=["水电补给", "遮阳棚", "车载冰箱", "排污管", "行车记录仪"],
        intensity=3,
    ),
    "budget": StyleProfile(
        key="budget", label="经济", spots_per_day=(5, 8),
        slot_hours=(4, 3.5, 3), stay_per_spot_h=1.0, day_span_h=(12, 15),
        budget_ratio={"交通": 0.35, "住宿": 0.18, "餐饮": 0.22, "门票": 0.08, "其他": 0.17},
        tone=["经济", "青旅", "性价比", "省钱", "夜班", "硬座"],
        gear_focus=["轻装", "锁", "洗漱包", "充电宝", "学生证"],
        intensity=4,
    ),
    "photo": StyleProfile(
        key="photo", label="摄影", spots_per_day=(2, 4),
        slot_hours=(3.5, 3.5, 2), stay_per_spot_h=2.5, day_span_h=(9, 12),
        budget_ratio={"交通": 0.24, "住宿": 0.32, "餐饮": 0.20, "门票": 0.10, "其他": 0.14},
        tone=["出片", "黄金时刻", "机位", "光影", "日出日落", "构图"],
        gear_focus=["相机", "三脚架", "ND滤镜", "备用电池", "灰卡", "快门线"],
        intensity=3,
    ),
    "study": StyleProfile(
        key="study", label="研学", spots_per_day=(2, 3),
        slot_hours=(3, 3, 2), stay_per_spot_h=2.5, day_span_h=(8, 10),
        budget_ratio={"交通": 0.22, "住宿": 0.30, "餐饮": 0.22, "门票": 0.16, "其他": 0.10},
        tone=["研学", "科普", "动手", "笔记", "讲解", "证书"],
        gear_focus=["笔记本", "放大镜", "标本袋", "研学手册", "望远镜"],
        intensity=2,
    ),
    "silver": StyleProfile(
        key="silver", label="银发", spots_per_day=(2, 3),
        slot_hours=(2.5, 2.5, 2), stay_per_spot_h=2.2, day_span_h=(7, 9),
        budget_ratio={"交通": 0.22, "住宿": 0.36, "餐饮": 0.26, "门票": 0.06, "其他": 0.10},
        tone=["慢节奏", "不累", "休息", "适老", "养生", "就近"],
        gear_focus=["常用药", "轮椅/拐杖", "保温杯", "急救卡", "舒适鞋"],
        intensity=1,
    ),
    "ski": StyleProfile(
        key="ski", label="滑雪", spots_per_day=(1, 2),
        slot_hours=(4.5, 3, 1), stay_per_spot_h=3.5, day_span_h=(9, 12),
        budget_ratio={"交通": 0.22, "住宿": 0.32, "餐饮": 0.20, "门票": 0.18, "其他": 0.08},
        tone=["滑雪", "雪道", "缆车", "雪具", "防风", "保暖"],
        gear_focus=["雪服", "雪镜", "手套", "护具", "防晒", "暖宝宝"],
        intensity=3,
    ),
    "island": StyleProfile(
        key="island", label="海岛", spots_per_day=(1, 3),
        slot_hours=(3, 3, 2.5), stay_per_spot_h=2.5, day_span_h=(7, 10),
        budget_ratio={"交通": 0.28, "住宿": 0.30, "餐饮": 0.22, "门票": 0.08, "其他": 0.12},
        tone=["海岛", "潜水", "浮潜", "沙滩", "出海", "日落"],
        gear_focus=["泳衣", "潜水镜", "防晒", "防水袋", "拖鞋", "晕船药"],
        intensity=2,
    ),
    "ancient": StyleProfile(
        key="ancient", label="古镇", spots_per_day=(2, 3),
        slot_hours=(3, 2.5, 2.5), stay_per_spot_h=2.2, day_span_h=(8, 10),
        budget_ratio={"交通": 0.20, "住宿": 0.34, "餐饮": 0.24, "门票": 0.10, "其他": 0.12},
        tone=["慢游", "青石板", "摇橹船", "茶馆", "老字号", "烟火气"],
        gear_focus=["舒适鞋", "油纸伞", "相机", "团扇"],
        intensity=2,
    ),
    "rail": StyleProfile(
        key="rail", label="高铁周边", spots_per_day=(3, 4),
        slot_hours=(3, 3, 2.5), stay_per_spot_h=1.8, day_span_h=(8, 11),
        budget_ratio={"交通": 0.34, "住宿": 0.26, "餐饮": 0.22, "门票": 0.10, "其他": 0.08},
        tone=["高铁", "周末", "周边", "说走就走", "短时", "citywalk"],
        gear_focus=["登车箱", "充电宝", "耳机", "零食"],
        intensity=2,
    ),
    # ── v0.0.3: 极限玩法 + 自然美景专线 ──
    "extreme": StyleProfile(
        key="extreme", label="极限运动", spots_per_day=(1, 2),
        slot_hours=(4, 3, 2), stay_per_spot_h=4.0, day_span_h=(8, 10),
        budget_ratio={"交通": 0.20, "住宿": 0.24, "餐饮": 0.14, "门票": 0.34, "其他": 0.08},
        tone=["肾上腺素", "持证教练", "装备检查", "安全红线", "红牛玩法", "天气窗口"],
        gear_focus=["头盔", "护具", "防晒", "运动相机", "保险(高风险条款)", "防水袋"],
        intensity=5,
    ),
    "nature": StyleProfile(
        key="nature", label="自然美景专线", spots_per_day=(2, 3),
        slot_hours=(4.5, 3, 1.5), stay_per_spot_h=2.5, day_span_h=(9, 12),
        budget_ratio={"交通": 0.32, "住宿": 0.26, "餐饮": 0.20, "门票": 0.08, "其他": 0.14},
        tone=["景观走廊", "晨雾光线", "日照金山", "补给点", "见站即补", "折返预案"],
        gear_focus=["相机", "防风分层", "补给", "双电源", "离线轨迹", "卫星通信(无人区)"],
        intensity=4,
    ),
    # ── v0.0.6: 演唱会（锚点事件型旅程） ──
    "concert": StyleProfile(
        key="concert", label="演唱会之旅", spots_per_day=(2, 3),
        slot_hours=(3, 3, 2), stay_per_spot_h=1.6, day_span_h=(7, 9),
        budget_ratio={"交通": 0.22, "住宿": 0.24, "餐饮": 0.18, "门票": 0.28, "其他": 0.08},
        tone=["锚点事件", "演出时刻固定", "先到先玩", "住场馆近", "散场交通", "官方周边"],
        gear_focus=["身份证", "门票截图", "充电宝", "润喉糖", "薄外套", "透明小包"],
        intensity=2,
    ),
}

# 出行方式 -> 推荐画像(用于未明确指定时的推断)
MODE_TO_STYLE = {
    "亲子游": "family", "家庭游": "family", "带孩子": "family", "带娃": "family",
    "朋友出行": "friends", "朋友": "friends", "结伴": "friends", "宿舍": "friends",
    "情侣": "couple", "情侣游": "couple", "两个人": "couple", "约会": "couple",
    "自驾": "roadtrip", "自驾游": "roadtrip", "开车": "roadtrip", "自驾车": "roadtrip",
    "骑车": "cycling", "骑行": "cycling", "自行车": "cycling", "单车": "cycling",
    "徒步": "hiking", "徒步游": "hiking", "爬山": "hiking", "登山": "hiking",
    "摩旅": "moto", "摩托车": "moto", "机车": "moto", "骑行摩托": "moto",
    "特种兵": "commando", "特种兵旅游": "commando", "暴走": "commando",
    "度假": "resort", "躺平": "resort", "休息": "resort", "放松": "resort",
    "散心": "relax", "心情不好": "relax", "治愈": "relax", "relax": "relax",
    "蜜月": "honeymoon", "度蜜月": "honeymoon", "新婚": "honeymoon", "纪念日": "honeymoon",
    "休闲": "leisure", "慢游": "leisure", "不赶": "leisure",
    # 扩展方式(国内全场景)
    "露营": "camping", "营地": "camping", "野营": "camping", "精致露营": "camping", "glamping": "camping",
    "房车": "rv", "房车游": "rv", "自驾房车": "rv",
    "经济游": "budget", "背包": "budget", "背包客": "budget", "省钱游": "budget", "青旅": "budget",
    "摄影": "photo", "旅拍": "photo", "出片": "photo", "拍照打卡": "photo", "风光摄影": "photo",
    "研学": "study", "游学": "study", "科普": "study", "亲子研学": "study", "夏令营": "study", "冬令营": "study",
    "银发": "silver", "适老": "silver", "老人": "silver", "爸妈游": "silver", "长辈": "silver",
    "滑雪": "ski", "冰雪": "ski", "雪场": "ski",
    "海岛": "island", "潜水": "island", "浮潜": "island", "海边": "island", "出海": "island",
    "古镇": "ancient", "水乡": "ancient", "慢游古城": "ancient", "古城游": "ancient",
    "高铁游": "rail", "周边游": "rail", "周末游": "rail", "微度假": "rail", "citywalk": "rail", "city walk": "rail",
    # v0.0.3: 极限玩法 + 自然美景专线
    "极限运动": "extreme", "冲浪": "extreme", "跳伞": "extreme", "蹦极": "extreme",
    "攀岩": "extreme", "速降": "extreme", "滑索": "extreme", "溪降": "extreme",
    "骑马": "extreme", "马背": "extreme", "射击": "extreme", "射击场": "extreme",
    "红牛玩法": "extreme", "肾上腺素": "extreme", "极限": "extreme",
    "自然美景": "nature", "风光线": "nature", "景观线": "nature", "景观走廊": "nature",
    "秘境": "nature", "大峡谷": "nature", "无人区": "nature", "雪山": "nature",
    "日照金山": "nature", "草原骑": "nature", "风景公路": "nature",
    # v0.0.6: 演唱会（锚点事件型旅程）
    "演唱会": "concert", "音乐会": "concert", "音乐节": "concert", "livehouse": "concert",
    "演出": "concert", "看演出": "concert", "观演": "concert", "歌迷": "concert",
    "巡演": "concert", "演唱会之旅": "concert",
}

# 住宿档次 -> 每人每晚住宿预算(元)
LODGING = {
    "青旅": (40, 90), "经济": (80, 150), "舒适": (200, 400),
    "高档": (500, 1000), "奢华": (1200, 3000),
}
# 餐饮档位 -> 每人每天(元)
FOOD = {"经济": (50, 90), "舒适": (100, 180), "高档": (250, 500), "奢华": (600, 1200)}


def load() -> list[dict]:
    return refloader.load("destinations.json")["destinations"]


def find(name: str, dests: list[dict]) -> dict | None:
    hits = [d for d in dests if d["name"] == name]
    if not hits:
        hits = [d for d in dests if name in d["name"] or d["name"] in name]
    if hits:
        return hits[0]
    # 具体山/景区名 -> 所属城市(数据里只有城市级目的地, 用户常直接说山名)
    spot = SPOT_TO_CITY.get(name)
    if spot:
        hits = [d for d in dests if d["name"] == spot]
        if hits:
            return hits[0]
    return None


# 具体爬山景区 -> 数据中已有的城市级目的地(用户说「玉龙雪山」时落到「丽江」)
SPOT_TO_CITY = {
    "玉龙雪山": "丽江", "玉龙": "丽江", "蓝月谷": "丽江", "虎跳峡": "丽江",
    "苍山": "大理", "苍山洱海": "大理", "洱海": "大理", "崇圣寺三塔": "大理",
    "梅里雪山": "香格里拉", "飞来寺": "香格里拉", "普达措": "香格里拉",
    "云杉坪": "丽江", "牦牛坪": "丽江", "老君山": "丽江",
    "石卡雪山": "香格里拉", "哈巴雪山": "香格里拉",
}


def infer_style(args) -> str:
    """从用户自由文本推断节奏画像。"""
    if args.style:
        return args.style
    blob = " ".join(args.hint or [])
    for k, v in MODE_TO_STYLE.items():
        if k in blob:
            return v
    return "leisure"


# ── 多意图识别: 同一句话常含多个诉求(自驾+爬山+日出+错峰),
# 引擎只能选一个「节奏画像」, 但其余诉求以「偏好块」形式注入报告, 不丢失。 ──
VALID_INTENTS = {"hiking", "sunrise", "avoid_crowd", "photo", "foodie", "culture"}
INTENT_KEYWORDS = {
    "hiking": ["爬山", "登山", "徒步", "攀", "暴走", "爬山"],
    "sunrise": ["日出", "看日出", "看日初", "朝霞", "晨曦", "看太阳"],
    "avoid_crowd": ["错峰", "避开人群", "避开人流", "人少", "不挤",
                    "避开高峰", "错开人群", "人少的地方", "不用人挤人"],
    "photo": ["拍照", "出片", "摄影", "旅拍", "美美的"],
    "foodie": ["美食", "吃", "小吃", "探店", "好吃"],
    "culture": ["文化", "古镇", "古建", "历史", "博物馆", "人文"],
}


def infer_intents(args) -> dict:
    """从用户原话(--hint)与显式 --tag 识别附加诉求。"""
    blob = " ".join(args.hint or [])
    intents: dict = {}
    for k, kws in INTENT_KEYWORDS.items():
        if any(w in blob for w in kws):
            intents[k] = True
    for t in (args.tag or []):
        if t in VALID_INTENTS:
            intents[t] = True
    return intents


def daily_spots(profile: StyleProfile, day_idx: int, total_days: int) -> int:
    """计算每日景点数。首末日减半(到达/离开日)。"""
    lo, hi = profile.spots_per_day
    if total_days == 1:
        n = (lo + hi) // 2
    elif day_idx == 0 or day_idx == total_days - 1:
        n = max(1, (lo + hi) // 3)
    else:
        n = (lo + hi) // 2
    return max(1, n)


# 骑行/徒步/摩旅: 「点」不是核心指标, 在途里程才是。
# 为这三种画像补充每日的「在途」元素, 避免出现"全天只有 3.8h"的失真结果。
ACTIVE_PROFILES = {"cycling", "hiking", "moto", "roadtrip", "rv"}
ACTIVE_ICON = {"cycling": "🚴", "hiking": "🥾", "moto": "🏍️", "roadtrip": "🚗", "rv": "🚐"}
ACTIVE_ADDON = {
    "cycling": {
        "label": "骑行里程",
        "range_km": (25, 45),
        "note": "按码表配速, 含途中休息与补给, 平路为主、爬坡集中在上午",
    },
    "hiking": {
        "label": "徒步距离",
        "range_km": (12, 22),
        "note": "含海拔爬升, 早出发避晒, 中途设补水点, 强度以当天气况为准",
    },
    "moto": {
        "label": "骑行里程",
        "range_km": (180, 320),
        "note": "含服务区与加油站停留, 控制节奏不赶夜路",
    },
    "roadtrip": {
        "label": "驾驶里程",
        "range_km": (180, 400),
        "note": "含服务区补给与沿途停留, 连续驾驶不超过 2 小时",
    },
    "rv": {
        "label": "房车移动里程",
        "range_km": (80, 200),
        "note": "房车限速低、停靠营地补给, 日均移动短, 优先选有水电桩的营地",
    },
}


def build_slots(profile: StyleProfile, spots: int) -> list[dict]:
    """把一天切成上午/下午/晚上三段, 分配景点数。

    时段长度随实际景点数缩放: 景点多则压缩单点停留、延长总时长;
    景点少则缩短总时长, 留白才是度假/休闲该有的样子。
    """
    am_h, pm_h, night_h = profile.slot_hours
    lo, hi = profile.spots_per_day
    span_lo, span_hi = profile.day_span_h

    # 密度系数: 相对该画像「常规密度」的缩放
    mid = (lo + hi) / 2
    density = spots / mid if mid else 1.0

    # 单点实际停留: 密度高则压缩, 但不低于 0.7h
    stay = max(0.7, profile.stay_per_spot_h / max(density, 0.6))

    # 上午/下午按比例分配景点
    ratio_am = am_h / (am_h + pm_h)
    am_s = max(1, round(spots * ratio_am))
    pm_s = max(1, spots - am_s)
    night_s = 0
    if profile.key not in ("resort", "relax", "leisure") and spots >= 4:
        night_s = 1
        pm_s = max(1, spots - am_s - 1)

    def seg(n: int, base_h: float) -> float:
        if n <= 0:
            return 0.0
        h = n * stay
        # 单段不超过基准时长(留出吃饭/通勤/休息)
        return round(min(h, base_h * 1.35), 1)

    slots = []
    # 起始时间随画像调整: 度假/蜜月不赶早, 特种兵/自驾早出发
    am_start = "09:30" if profile.key in (
        "resort", "relax", "leisure", "honeymoon", "silver", "island",
        "camping", "ancient", "study", "ski", "rv",
    ) else "08:30"
    if am_s:
        slots.append({
            "name": "上午", "spots": am_s, "start": am_start,
            "hours": seg(am_s, am_h),
            "per_spot": round(stay, 1),
            "note": _slot_note(profile, "上午", am_s),
        })
    if pm_s:
        slots.append({
            "name": "下午", "spots": pm_s, "start": "13:30",
            "hours": seg(pm_s, pm_h),
            "per_spot": round(stay, 1),
            "note": _slot_note(profile, "下午", pm_s),
        })
    if night_s:
        slots.append({
            "name": "晚上", "spots": night_s, "start": "18:30",
            "hours": seg(night_s, night_h),
            "per_spot": round(stay, 1),
            "note": _slot_note(profile, "晚上", night_s),
        })
    return slots


def _slot_note(profile: StyleProfile, slot: str, spots: int) -> str:
    """时段说明随画像与实际密度变化, 避免「1 个点却说主攻核心」的错位。"""
    if spots <= 1:
        return {
            "上午": "一个慢点, 慢慢逛, 别赶",
            "下午": "留白时间, 咖啡馆/民宿发呆/周边散步",
            "晚上": "早点休息或附近夜逛",
        }[slot]
    if profile.key == "commando":
        return {
            "上午": "密集打卡, 趁人少光线好",
            "下午": "连打几处, 含简餐, 压缩休息",
            "晚上": "夜市/夜景, 注意末班车",
        }[slot]
    if profile.key == "roadtrip":
        return {
            "上午": "早出发, 沿途风景优先, 服务区补给",
            "下午": "边开边停, 日落前到观景点",
            "晚上": "抵达后吃饭休整",
        }[slot]
    if profile.key in ("resort", "relax", "leisure"):
        return {
            "上午": "自然醒, 一个主活动足矣",
            "下午": "不设闹钟, 随性安排",
            "晚上": "就近晚餐, 早点回住处",
        }[slot]
    if profile.key == "hiking":
        return {
            "上午": "早出发避晒, 主攻山线路段",
            "下午": "控制强度, 设补给点, 不硬撑",
            "晚上": "下山后拉伸, 早休",
        }[slot]
    if profile.key == "cycling":
        return {
            "上午": "趁凉快骑, 爬坡放上午, 注意防晒",
            "下午": "含午餐与补水点, 午后风大减速",
            "晚上": "就近晚餐, 检查车况与电量",
        }[slot]
    if profile.key == "moto":
        return {
            "上午": "早出发, 趁凉快跑, 弯道多减速",
            "下午": "控制节奏, 加油站与驿站休整",
            "晚上": "不赶夜路, 找好落脚点",
        }[slot]
    if profile.key in ("family", "couple", "honeymoon"):
        return {
            "上午": "安排 1-2 个轻松点",
            "下午": "含午餐与休息, 留出自由时间",
            "晚上": "安排一场有仪式感的活动",
        }[slot]
    return {
        "上午": "趁人少光线好, 主攻核心",
        "下午": "含午餐, 避开日头",
        "晚上": "夜景/夜市, 注意末班",
    }[slot]


# ── 住宿与房间分配 ────────────────────────────────────────────
# 关键: 一家三口/四口通常只住一间(家庭房可睡3-4人), 不是"人数=房间数"。
# 这是行程合理性的核心 —— 按人算房价会严重高估预算。


@dataclass
class StayPlan:
    rooms: int                # 房间数
    room_types: list          # 每间房的床型建议
    rationale: str            # 分配理由(会写进报告)
    per_room_night: tuple     # 每间每晚价位
    tips: list                # 预订提示


def stay_plan(people: int, profile: StyleProfile, composition: str = "",
              lodging: str = "舒适") -> StayPlan:
    """按人数、关系构成与性别智能计算房间数与床型。

    composition 传入用户描述, 如 "三口" "二大一小" "情侣" "兄弟俩" "姐妹团"
    "两对情侣" "和朋友及其对象" "带父母" 等。未传则按 people 推断。

    智能分房三原则:
    1. 伴侣/情侣 → 合住大床房; 多对情侣 → 每对 1 间。
    2. 同性朋友(兄弟/姐妹/哥们/闺蜜) → 合住双床房省钱且自然。
    3. 异性非伴侣(同事/普通朋友/长辈与成年子女) → 分房, 避免尴尬。
    """
    comp = composition or ""
    lo, hi = LODGING.get(lodging, LODGING["舒适"])

    # 户外/骑行/摩旅人群通常装备多, 倾向单间; 休闲度假多人常合住别墅
    solo_oriented = profile.key in ("moto", "cycling", "hiking", "commando", "roadtrip")

    # ── 团体（有组织方：团建/研学/夕阳红/俱乐部/定制团）→ 组织者统订标准间按性别拼 ──
    if any(k in comp for k in _GROUP_KW):
        rooms = max(1, (people + 1) // 2)
        types = [f"标准双床间 ×{rooms}(组织者统一预订, 按性别/级别拼房)"]
        why = f"团体出行({people} 人)由组织者统一订 {rooms} 间标准双床间并按性别拼房，比各自下单更好管理与议价"
        tips = [
            "统一开一张/多张同抬头发票，便于公司报销或包价结算",
            "要求同楼层或相邻房间，方便集合点名与夜间照应",
            "领队/导游同住便于应急；确认每间独立卫浴与每房入住上限(多 2-3 人)",
            "旺季/热门研学基地提前 2-3 周锁房，留团队取消政策缓冲",
        ]
    # ── 智能分房: 多对情侣 (每对 1 间大床房) ──
    elif any(k in comp for k in ("两对情侣", "两对夫妻", "两对", "3对", "三对", "4对", "四对")):
        pairs = 2
        for k, n in (("三对", 3), ("3对", 3), ("四对", 4), ("4对", 4)):
            if k in comp:
                pairs = n
        rooms = pairs
        types = [f"大床房 ×{pairs}(每对 1 间)"]
        why = f"{pairs} 对情侣/夫妻每对 1 间大床房(1.8m), 独立空间是关系型出行的刚需"
        tips = [
            "尽量订相邻或同楼层房间, 方便互相照应",
            "纪念日/蜜月可让酒店统一备注, 部分酒店有免费布置",
            "预算紧时其中一对可换双床房降档, 但不建议两对挤一间",
        ]
    # ── 智能分房: 异性朋友/同事同行 → 分房 ──
    elif any(k in comp for k in ("异性", "同事", "普通朋友", "网友见面", "搭子")):
        rooms = max(2, (people + 1) // 2)
        types = [f"双床房 ×{rooms}"]
        why = "异性朋友/同事非伴侣关系, 分房入住更稳妥得体, 避免同行尴尬"
        tips = [
            "分房预算更高, 订相邻房间平衡便利与私密",
            "部分酒店可开具多间独立发票, 出差/AA 报销友好",
        ]
    # ── 智能分房: 兄弟/哥们等男性朋友 → 合住双床房 ──
    elif any(k in comp for k in ("兄弟", "哥们", "男友人", "男的")):
        if people <= 2:
            rooms, types = 1, ["双床房(2 张 1.2-1.35m 床)"]
            why = "兄弟俩 1 间双床房, 各睡一床最自在, 比两间省一半"
            tips = [
                "想再省可订青旅双人间(¥80-140), 但隔音与卫生打折",
                "打游戏/看球夜聊的话确认房间隔音, 选走廊尽头的安静房",
                "摩旅/骑行装备多时优先选空间大的房型并确认有晾衣区",
            ]
        elif people <= 4:
            rooms, types = 2, ["双床房 ×2"]
            why = f"{people} 位兄弟分住 2 间双床房(2 人/间), 既省钱又有各自空间"
            tips = ["要求相邻房间, 夜宵局方便串门", "民宿整栋/麻将房多人性价比更高"]
        else:
            rooms = (people + 1) // 2
            types = [f"双床房 ×{rooms}"]
            why = f"{people} 人分住 {rooms} 间双床房; 民宿整栋通常更划算"
            tips = ["6 人以上直接找民宿整栋/多间连通房, 人均可压到 ¥80-120"]
    # ── 智能分房: 姐妹/闺蜜等女性朋友 → 合住双床房 + 女性友好 ──
    elif any(k in comp for k in ("姐妹", "闺蜜", "女友人", "女生", "宝妈")):
        if people <= 2:
            rooms, types = 1, ["双床房(2 张 1.2-1.35m 床)"]
            why = "姐妹/闺蜜 1 间双床房, 合住方便夜聊试装拍照, 比两间省一半"
            tips = [
                "优先女性友好酒店/民宿: 24h 前台、走廊监控、独卫单间",
                "青旅选女生间(多数正规青旅分性别), 贵重物品锁柜",
                "拍照出片需求高时选有浴缸/大飘窗/景观阳台的房型",
            ]
        else:
            rooms = (people + 1) // 2
            types = [f"双床房 ×{rooms}"]
            why = f"{people} 位姐妹分住 {rooms} 间双床房(2 人/间), 平衡省钱与舒适"
            tips = ["多人女性出行优先连锁品牌酒店, 安全与卫生下限更高"]
    # ── 智能分房: 带父母/长辈 → 长辈单独房 ──
    elif any(k in comp for k in ("父母", "爸妈", "老人", "长辈", "岳父", "岳母", "公婆")) and people >= 3:
        rooms = 2
        types = ["长辈房 ×1(低楼层/近电梯/大床)", "子女房 ×1(双床或大床)"]
        why = "长辈单独 1 间(选低楼层近电梯, 睡眠浅怕吵), 子女 1 间; 两间相邻便于照应, 又互不打扰作息"
        tips = [
            "长辈房优先: 低楼层(电梯故障时省爬楼)、近电梯但不贴电梯井、远离 KTV/马路",
            "确认酒店有无无障碍通道与防滑地垫, 浴室建议带扶手",
            "两间房务必同楼层相邻, 晚上照应方便",
            "若长辈习惯早起, 子女房隔音也要好——错峰作息是家庭出行最大矛盾",
        ]
    elif any(k in comp for k in ("三口", "一家三口", "二大一小", "一大一小", "亲子", "带娃")):
        rooms = 1
        types = ["家庭房 / 双床房+加床(1.35m或1.5m大床 + 单人床)"]
        why = "三口之家订1 间家庭房或双床加床即可, 房间面积通常比 2 间标准房更宽敞, 且小孩与父母同住便于照看"
        tips = [
            "预订时明确告知「2 大 1 小」，确认酒店是否提供儿童床/加床（部分免费、部分需另收费）",
            "优先选家庭房：多为 1.5m 大床 + 0.9m 单床，部分含儿童洗漱用品与拖鞋",
            "若酒店无家庭房，可订「双床房」并申请加床，注意确认加床后房间是否拥挤",
            "带 3 岁以下婴儿需确认婴儿床是否提供、是否免费",
        ]
    elif any(k in comp for k in ("两大两小", "四口", "一家四口", "二女", "二子")):
        rooms = 1
        types = ["家庭套房 / 两室一厅(内含2 张床 + 客厅沙发床)"]
        why = "四口之家宜订家庭套房(两室一厅)，亲子分区睡，避免两个孩子与父母挤一张床"
        tips = [
            "四口人建议选两室一厅或带上下铺的家庭房，孩子单独睡一间或上下铺更舒适",
            "确认房间最大入住人数，含加床后是否超限（多数酒店 3 人/间是上限）",
            "四口之家对房型要求高，热门景区（黄山、张家界等）务必提前 2-3 周订，旺季房源紧",
        ]
    elif any(k in comp for k in ("情侣", "二人", "两个人", "蜜月", "新婚")):
        rooms = 1
        types = ["大床房(1.8m 床)"]
        why = "2 人 1 间大床房，蜜月建议选带浴缸或景观房"
        tips = [
            "蜜月/纪念日建议提前备注，酒店多有免费布置（花瓣、蛋糕、红酒）",
            "大床房优先 1.8m 以上床宽，1.5m 偏窄",
            "度假村/海景房建议选高楼层，避开电梯井与设备间噪音",
        ]
    elif any(k in comp for k in ("朋友", "结伴", "一群", "宿舍", "同学", "哥们")) or people >= 3:
        if people <= 2:
            rooms = 1
            types = ["双床房(2 张 1.2m 床)"]
            why = "2 人 1 间双床房"
            tips = ["确认是否需双床，订大床房时备注即可"]
        elif people <= 4:
            rooms = 2
            types = ["双床房 ×2", "或 1 间四人家庭房"]
            why = f"{people} 人分住 2 间双床房（同行者各自舒适）；若预算允许也可直接订一间家庭房"
            tips = [
                "同住 2 间比 1 间大床更舒适，尤其是朋友/同事出行",
                "订双床房并备注「同行安排」，多数酒店可安排相邻房间",
            ]
        else:
            rooms = (people + 1) // 2
            types = [f"双床房 ×{rooms}"]
            why = f"{people} 人需 {rooms} 间双床房（每间住 2 人）"
            tips = [
                "人数较多时优先考虑民宿整栋或家庭套房，整体比连锁酒店便宜且有公共空间",
                "提前确认每间房是否都有独立卫浴，5 人以上建议 3 间以内便于管理",
            ]
    else:
        rooms = max(1, (people + 1) // 2)
        types = ["双床房" if rooms > 1 else "大床房"]
        why = f"{people} 人约需 {rooms} 间"
        tips = ["单人出行订大床房即可"]

    if solo_oriented and rooms == 1:
        tips.append("户外/摩旅出行装备较多，确认房间有无衣架与晾衣空间，必要时选带行李间的房型")

    return StayPlan(rooms=rooms, room_types=types, rationale=why,
                    per_room_night=(lo, hi), tips=tips)


def budget_for(profile: StyleProfile, days: int, people: int,
               lodging: str, food: str, transport_note: str = "",
               stay: StayPlan | None = None) -> dict:
    """预算计算。**住宿按房间数计, 不按人数计** —— 这是合理性关键。

    三口之家 1 间家庭房住 3 人, 若按 3 人×每晚房价 会高估近 2 倍。
    """
    lo_l, hi_l = LODGING.get(lodging, LODGING["舒适"])
    lo_f, hi_f = FOOD.get(food, FOOD["舒适"])
    rooms = stay.rooms if stay else max(1, (people + 1) // 2)

    # 住宿: 按间/晚 × 间数 × 晚数。当天来回(days=1)晚数为 0, 无住宿支出。
    nights = max(0, days - 1)
    room_mid = (lo_l + hi_l) / 2
    lodging_total = room_mid * rooms * nights

    # 餐饮: 按人数 (每人每天)
    food_mid = (lo_f + hi_f) / 2
    food_total = food_mid * people * days

    # 门票: 按人数, 强度越高买票越多; 儿童通常半价, 故按 0.8 折算
    child_factor = 0.8 if profile.key == "family" else 1.0
    ticket_total = 60 * people * days * (profile.intensity / 3) * child_factor

    # 交通: 按人数, 但自驾/摩旅按车计更合理
    if profile.key in ("roadtrip", "moto", "rv", "camping"):
        base_transport = {  # 每人机票/火车 + 车辆/营地分摊
            "commando": 800, "leisure": 1200, "resort": 1800, "honeymoon": 2500,
            "roadtrip": 900, "cycling": 400, "hiking": 500, "moto": 600,
            "family": 1100, "couple": 1500, "friends": 1000,
            "rv": 900, "camping": 500, "relax": 1500,
        }.get(profile.key, 900)
    else:
        base_transport = 800
    transport_total = base_transport * people

    other_total = (lodging_total + food_total) * profile.budget_ratio["其他"] / max(
        profile.budget_ratio["住宿"] + profile.budget_ratio["餐饮"], 0.1)

    breakdown = {
        "交通": round(transport_total),
        "住宿": round(lodging_total),
        "餐饮": round(food_total),
        "门票": round(ticket_total),
        "其他": round(other_total),
    }
    total = sum(breakdown.values())
    return {
        "group": breakdown,
        "per_person": {k: round(v / people) for k, v in breakdown.items()},
        "per_person_total": round(total / people),
        "group_total": round(total),
        "lodging_level": lodging,
        "food_level": food,
        "rooms": rooms,
        "nights": nights,
        "note": transport_note,
        "lodging_basis": (f"{rooms} 间 × {nights} 晚（按房间计, 非按人数）"
                          if nights > 0 else "当天来回无住宿（0 晚）"),
    }


GEAR_BASE = {
    "证件": ["身份证", "现金/银行卡", "手机+充电器"],
    "衣物": ["换洗衣物", "舒适鞋", "外套(昼夜温差)"],
    "防护": ["防晒霜", "墨镜", "帽子", "雨伞/雨衣"],
    "健康": ["常用药", "创可贴", "晕车药(自驾)"],
    "电子": ["充电宝", "数据线", "耳机"],
}


def gear_for(profile: StyleProfile, season: str = "") -> dict:
    """按画像生成物料清单, 分必带/建议/季节性。"""
    g = {k: list(v) for k, v in GEAR_BASE.items()}
    focus = {
        "commando": ["速干T恤", "运动鞋", "大容量水壶", "能量棒", "快干毛巾"],
        "leisure": ["折叠椅", "保温杯", "相机", "速干毛巾", "小零食"],
        "resort": ["泳衣", "浴巾", "人字拖", "遮阳帽", "防水袋", "防晒喷雾"],
        "relax": ["书", "耳机", "舒适鞋", "保温杯", "眼罩", "日记本"],
        "honeymoon": ["情侣装/正装", "拍立得", "红酒/巧克力", "香薰", "花束"],
        "roadtrip": ["行车记录仪", "充气泵", "拖车绳", "三角警示牌", "车载急救包", "保温箱", "颈枕"],
        "cycling": ["头盔", "骑行服", "码表", "补胎工具", "骑行手套", "反光条", "骑行水壶", "防晒袖套"],
        "hiking": ["登山杖", "徒步鞋", "护膝", "头灯", "雨衣", "GPS/轨迹", "能量胶", "防虫液", "应急毯"],
        "moto": ["头盔(全盔)", "骑行服", "护膝护肘", "防风衣", "摩托车手套", "工具包", "补胎工具", "拖车带", "反光背心"],
        "family": ["儿童雨衣", "湿巾", "零食", "常用儿童药", "推车", "保温壶", "玩具", "围兜"],
        "couple": ["氛围穿搭", "微单/相机", "野餐垫", "三脚架", "防晒", "小礼物"],
        "friends": ["聚会零食", "酒水", "蓝牙音箱", "扑克/桌游", "充电宝", "换洗T恤"],
        "camping": ["帐篷地钉", "防风绳", "营地灯", "焚火台", "冰桶", "垃圾袋", "防潮坐垫"],
        "rv": ["水电连接线", "遮阳棚锚", "车载逆变器", "黑水箱", "折叠踏步", "燃气罐"],
        "budget": ["压缩毛巾", "洗衣液", "挂锁", "分装瓶", "泡面", "颈枕"],
        "photo": ["相机机身", "主力镜头", "备用机身电池", "ND/CPL滤镜", "反光板", "防水相机包"],
        "study": ["研学手册", "放大镜", "标本夹", "彩色笔", "姓名贴", "任务卡"],
        "silver": ["分药盒", "血压计", "舒适软底鞋", "折叠凳", "老花镜", "急救联系卡"],
        "ski": ["雪服雪裤", "速干内层", "雪镜", "头盔", "手套", "雪袜", "暖贴"],
        "island": ["潜水衣", "面镜呼吸管", "防水手机袋", "沙滩巾", "风油精", "晒后修复"],
        "ancient": ["软底绣花鞋", "油纸伞", "团扇", "汉服(可选)", "相机", "小零钱"],
        "rail": ["20寸登车箱", "颈枕", "眼罩耳塞", "充电宝", "湿巾", "零食"],
    }
    g["画像重点"] = focus.get(profile.key, [])
    seasonal = {
        "夏": ["防晒霜SPF50+", "墨镜", "遮阳帽", "驱蚊液", "速干衣", "便携小风扇"],
        "冬": ["羽绒服", "暖宝宝", "防滑鞋", "厚袜", "保温杯", "护踝"],
        "春": ["薄外套", "雨伞(梅雨)", "防花粉口罩"],
        "秋": ["薄羽绒", "围巾", "润唇膏", "徒步鞋(防滑)"],
    }
    g["季节性"] = seasonal.get(season, []) if season else []
    return g


def special_advice(profile: StyleProfile) -> dict | None:
    """自驾/房车/摩旅的限行限高/禁摩建议(经验参考, 需出行前核实)。"""
    r = load_restrictions()
    if not r:
        return None
    if profile.key == "rv":
        blk = r.get("rv", {})
        return {
            "kind": "rv",
            "title": "房车限行 · 限高",
            "items": [
                {"主题": "限高", "内容": blk.get("限高", "")},
                {"主题": "限行", "内容": blk.get("限行", "")},
                {"主题": "停靠", "内容": blk.get("停靠", "")},
            ],
        }
    if profile.key == "roadtrip":
        blk = r.get("car_plate", {})
        return {
            "kind": "car_plate",
            "title": "自驾 · 车牌/区域限行",
            "items": [{"主题": "概述", "内容": blk.get("desc", "")}] +
                    [{"主题": f"提示{i+1}", "内容": t} for i, t in enumerate(blk.get("tips", []))],
        }
    if profile.key == "moto":
        blk = r.get("moto", {})
        return {
            "kind": "moto",
            "title": "摩旅 · 禁摩/车型限行",
            "items": [{"主题": "概述", "内容": blk.get("desc", "")}] +
                    [{"主题": f"提示{i+1}", "内容": t} for i, t in enumerate(blk.get("tips", []))],
        }
    return None


# ── v0.0.6: 演唱会（锚点事件型旅程） ──
CONCERT_DATA = DATA.parent / "concert_playbook.json"


def load_concert() -> dict:
    with open(CONCERT_DATA, encoding="utf-8") as f:
        return json.load(f)["concert_trip"]


def concert_show_day(days: int) -> int:
    """演出日定位：1 天当天到当天看；2 天首日看（次日补玩返程）；
    3 天及以上放中间（前后都有缓冲）。返回 0-based 日索引。"""
    if days <= 2:
        return 0
    return 1


def concert_anchor(days: int, people: int) -> dict:
    """生成演唱会旅程的锚点决策块：到达时间决策树 + 住宿策略 + 观演贴士 + 天数模板。"""
    d = load_concert()
    tpl_key = "1" if days == 1 else ("2" if days == 2 else ("3" if days == 3 else "4+"))
    return {
        "principle": d["principle"],
        "show_day": concert_show_day(days) + 1,  # 1-based，给渲染用
        "arrival_rule": d["arrival_rule"],
        "show_day_template": d["show_day_template"],
        "stay_strategy": d["stay_strategy"],
        "logistics": d["logistics"],
        "days_template": {"label": d["days_templates"]["label"],
                          "text": d["days_templates"][tpl_key]},
        "packing_extra": d["packing_extra"],
    }


def build(args) -> dict:
    dests = load()
    style_key = infer_style(args)
    if style_key not in STYLE_PROFILES:
        valid = ", ".join(sorted(STYLE_PROFILES.keys()))
        print(f"ERROR: unknown style '{style_key}'. Valid styles: {valid}", file=sys.stderr)
        sys.exit(1)
    profile = STYLE_PROFILES[style_key]
    intents = infer_intents(args)

    # 受众维度: 用户不问也先准备(男性/女性/家庭/老人/通用)
    aud_key = (args.audience or "").strip() or infer_audience(args)
    aud_db = load_audience()
    aud_blk = aud_db.get(aud_key, aud_db.get("general", {}))
    aud_label = aud_blk.get("label", "通用出行者")
    aud_focus = aud_blk.get("focus", [])
    aud_like = aud_blk.get("like", [])
    aud_avoid = aud_blk.get("avoid", [])
    aud_tips = aud_blk.get("tips", [])
    aud_ages = aud_blk.get("ages", {})
    aud_band = resolve_family_band(args.composition) if aud_key == "family" else ""
    aud_band_tips = aud_ages.get(aud_band, []) if aud_key == "family" else []

    # ── 出行陪伴结构（Party Type）·与 audience/style/theme 正交 ──
    party_db = load_party()
    _party_override = (getattr(args, "party", "") or "").strip()
    party_type = resolve_party_type(args.people, args.composition, args.hint, _party_override)
    party = party_block(party_db, party_type, args.people, inferred=not _party_override)

    targets = []
    # 连写多目的地自动拆分: "丽江大理香格里拉" → ["丽江","大理","香格里拉"]
    all_names = sorted((d["name"] for d in dests), key=len, reverse=True)

    def split_concat(s: str) -> list[str]:
        """按目的地库名最长匹配切分连写字符串; 切不开则原样返回。"""
        out, rest = [], s
        while rest:
            hit = next((n for n in all_names if rest.startswith(n)), None)
            if hit:
                out.append(hit)
                rest = rest[len(hit):]
            else:
                # 找不到前缀命中: 若已有部分命中则剩余作为整体, 否则整串返回
                if out:
                    out.append(rest)
                    rest = ""
                else:
                    return [s]
        return out or [s]

    expanded = []
    for t in args.to:
        if t in all_names or len(t) <= 4:
            expanded.append(t)
        else:
            parts = split_concat(t)
            # 拆分后每个都能命中目的地库才采用, 否则保留原串(防误拆)
            if all(find(p, dests) for p in parts) and len(parts) > 1:
                expanded.extend(parts)
            else:
                expanded.append(t)

    for t in expanded:
        d = find(t, dests)
        if d:
            targets.append(d)
        else:
            targets.append({"name": t, "region": "?", "summary": "", "url": "", "lat": None, "lon": None})

    days = args.days
    # 演唱会画像: 演出日为全程锚点, 该日压轻量、插入时间线提示
    show_day_idx = concert_show_day(days) if profile.key == "concert" else -1
    plan = []
    for i in range(days):
        spots = daily_spots(profile, i, days)
        if i == show_day_idx:
            spots = min(spots, 1)  # 演出日白天最多 1 个轻量点
        slots = build_slots(profile, spots)
        day = {
            "day": i + 1,
            "label": (("演出日" if i == show_day_idx else "抵达日") if i == 0
                      else ("演出日" if i == show_day_idx
                            else ("返程日" if i == days - 1 and days > 1 else "游玩日"))),
            "city": targets[min(i, len(targets) - 1)]["name"] if targets else "",
            "spots": spots,
            "total_hours": round(sum(s["hours"] for s in slots), 1),
            "slots": slots,
            "note": _day_note(profile, i, days) + _aud_nudge(aud_key),
        }
        # 骑行/徒步/摩旅/自驾: 附加当日在途里程
        if profile.key in ACTIVE_PROFILES:
            lo, hi = ACTIVE_ADDON[profile.key]["range_km"]
            first_last = (i == 0 or i == days - 1)
            mid = (lo + hi) / 2
            km = round(mid * (0.5 if first_last else 1.0))
            day["active"] = {
                "label": ACTIVE_ADDON[profile.key]["label"],
                "km": km,
                "note": ACTIVE_ADDON[profile.key]["note"],
            }
        # 日出意图: 首日清晨 slot 强调观日出机位
        if intents.get("sunrise") and i == 0 and slots:
            slots[0]["note"] = ("📸 首日即奔东向开阔机位看日出（湖畔/山脊/垭口），"
                                "提前查当日日出时间 40-60min 到场，前一晚住近观景点更省路程")
        # 演唱会画像: 演出日 slot 标注锚点时间线
        if i == show_day_idx and slots:
            slots[0]["note"] = ("🎤 演出日·上午轻量活动（不爬山不暴走保存体力）；"
                                "15:30 起转入演出节奏：取周边→早晚饭→18:15 入场安检")
            if len(slots) > 1:
                slots[-1]["note"] = ("🎤 晚间为演出时段（票面时间为准，按 19:30 基准平移）："
                                     "提前 60-90min 到场安检，散场步行 1 站再打车避开溢价")
        plan.append(day)

    season = args.season

    # 多意图偏好块: 引擎只选单一节奏画像, 但附加诉求(爬山/日出/错峰等)以偏好块保留
    prefs = []
    if intents.get("sunrise"):
        prefs.append({"主题": "日出优先", "内容": "每日首发机位选东向开阔点（湖畔/山脊/垭口），"
                     "提前查当日日出时间 40-60min 到场；前一晚尽量住近观景点以省路程。"})
    if intents.get("avoid_crowd"):
        prefs.append({"主题": "错峰策略", "内容": "① 早 8 点前入园/进山，避开 10-15 点高峰；"
                     "② 热门环线反向走（逆时针）；③ 工作日优于周末；④ 用冷门替代点分流。"})
    if intents.get("hiking"):
        prefs.append({"主题": "爬山节奏", "内容": "每日排 1 条主徒步线，早出发避晒，"
                     "设补水与下撤点，量力而行不硬撑；高海拔注意慢行与防风。"})
    if intents.get("photo"):
        prefs.append({"主题": "出片机位", "内容": "黄金时刻（日出后 1h/日落前 1h）留给出片点，"
                     "正午转室内或补觉存卡。"})
    if intents.get("foodie"):
        prefs.append({"主题": "美食动线", "内容": "把本地小吃/夜市排进傍晚与返程日，错峰用餐更松。"})
    if intents.get("culture"):
        prefs.append({"主题": "人文穿插", "内容": "每日穿插 1 处古镇/展馆/非遗点，平衡体力与体验。"})

    # 受众维度(用户不问也先准备): 把焦点/避坑/贴士转成可执行偏好块
    if aud_key != "general":
        if aud_focus:
            prefs.append({"主题": f"{aud_label}·关注", "内容": "；".join(aud_focus)})
        if aud_avoid:
            prefs.append({"主题": f"{aud_label}·避坑", "内容": "；".join(aud_avoid)})
        if aud_key == "family" and aud_band_tips:
            prefs.append({"主题": f"家庭·年龄段({aud_band})", "内容": "；".join(aud_band_tips)})

    # 冷知识 + 趣味建议: 按目的地匹配, 并始终附上"通用交通"; --no-fun 时整体不输出
    cold_db = load_cold()
    cold_out = []
    seen = set()
    for t in targets:
        nm = t.get("name")
        entry = cold_db.get(nm) if nm else None
        if entry and nm not in seen:
            seen.add(nm)
            cold_out.append({"dest": nm, "facts": entry.get("facts", []),
                             "fun": entry.get("fun", [])})
    gen = cold_db.get("通用交通") or cold_db.get("通用")
    if gen:
        cold_out.append({"dest": "通用", "facts": gen.get("facts", []),
                         "fun": gen.get("fun", [])})
    cold = cold_out if not getattr(args, "no_fun", False) else []

    # ── v0.1.1 摩旅模式：门禁自检 + 线路候选 ──
    moto_block = None
    if profile.key == "moto" and _MOTO_AVAILABLE:
        kms = [d.get("active", {}).get("km") for d in plan if d.get("active")]
        auto_daily = max((k for k in kms if k), default=None)
        auto_total = sum(k for k in kms if k) or None
        moto_block = moto_card(
            from_city=args.origin,
            to_city=targets[0]["name"] if targets else None,
            via_cities=[t["name"] for t in targets[1:]],
            daily_km=args.moto_daily_km or auto_daily,
            total_km=auto_total,
            displacement_cc=args.moto_cc,
            range_km=args.moto_range,
            has_license=True if args.moto_license else None,
            license_class=args.moto_license,
            has_plate=True if args.moto_docs else None,
            has_insurance=True if args.moto_docs else None,
            has_helmet=True if args.moto_helmet else None,
            prefer_highway=getattr(args, "moto_prefer_highway", False),
        )
        # 线路候选：先按目的地名匹配库内线路；匹配不上再按天数给同量级参考。
        # 用户没问线路时也可能用得上（「摩旅去西藏」直接命中 318/滇藏线）。
        names = [t.get("name") or "" for t in targets]
        hit = []
        for r in moto_suggest_routes(limit=99):
            blob = (r.get("region") or "") + (r.get("path") or "") + (r.get("name") or "")
            if any(n and n in blob for n in names):
                hit.append(r)
        moto_block["routes"] = (hit or moto_suggest_routes(days=days, limit=3))[:3]

        # 线路候选已定，接着做两件 v0.1.2 新增的事：
        # ① 绿荫优先排序/筛选（学备用地图服务智能体：暴晒是摩托党大敌，选线阶段就该管）
        #    纪律：绿荫偏好只作用于【已按目的地匹配出来的候选】，不拿全库线路覆盖匹配结果。
        if getattr(args, "moto_shade_first", False) or getattr(args, "moto_shade_min", None):
            pool = hit or moto_suggest_routes(days=days, limit=99)
            smin = getattr(args, "moto_shade_min", None)
            if smin:
                pool = [r for r in pool
                        if (moto_suggest_routes_shade_rank(r) >= _SHADE_FLOOR.get(smin, 0))]
            if getattr(args, "moto_shade_first", False):
                pool.sort(key=lambda r: (-moto_suggest_routes_shade_rank(r),
                                         int(r.get("level", 5)), -int(r.get("km", 0))))
            if not pool:  # 绿荫条件下无匹配 → 回退普通候选，不硬凑也不打乱目的地匹配
                pool = hit or moto_suggest_routes(days=days, limit=3)
            moto_block["routes"] = pool[:3]
        # ② 出行前待核实清单（数据增强通道：库只写稳定事实，会过期的必须现查）
        if _MOTO_ENRICH_AVAILABLE:
            cl = moto_build_checklist(
                from_city=args.origin,
                to_city=targets[0]["name"] if targets else None,
                via_cities=[t["name"] for t in targets[1:]],
                days=days,
                routes=moto_block["routes"])
            notes = []
            notes_path = getattr(args, "moto_notes", None)
            if notes_path:
                try:
                    raw = json.loads(Path(notes_path).read_text(encoding="utf-8"))
                    notes = moto_validate_notes(raw)
                except Exception as e:
                    notes = [{"_errors": [{"index": -1, "topic": "文件读取/解析失败",
                                           "error": str(e)}]}]
            moto_block["enrichment"] = {"checklist": cl, "notes": notes}

    # ── v0.1.13 房车/自驾后勤自检：rv 画像必出；roadtrip 画像在用户声明车型时也出 ──
    rv_block = None
    vtype = getattr(args, "vehicle_type", None)
    want_rv = (profile.key == "rv") or (profile.key == "roadtrip" and vtype)
    # 用户在非 rv/roadtrip 画像下传了 --rv-* 或 --vehicle-type：不能静默吞掉（尤其 --rv-tow 可能是违法上路信号）
    _rv_flags = [f for f in ("rv_length", "rv_mass", "rv_license", "rv_tow", "rv_height",
                             "rv_water", "rv_battery", "rv_ac", "rv_no_ac", "rv_dump_plan",
                             "rv_peak", "rv_booked", "rv_low_clearance", "rv_black_tank")
                 if getattr(args, f, None)]
    if (vtype or _rv_flags) and not want_rv:
        print(f"⚠ 提示：当前画像「{profile.label}」不生成房车/自驾后勤卡，"
              f"已忽略 --vehicle-type/--rv-* 参数（{', '.join(_rv_flags) or vtype}）。"
              f"如需后勤自检请用 --style rv 或 --style roadtrip --vehicle-type <车型>。",
              file=sys.stderr)
    if want_rv and _RV_AVAILABLE:
        # 未声明车型时，rv 画像默认按房车；roadtrip 用用户声明的车型
        vt = vtype or ("rv" if profile.key == "rv" else None)
        kms = [d.get("active", {}).get("km") for d in plan if d.get("active")]
        auto_total = sum(k for k in kms if k) or None
        rv_block = rv_card(
            vehicle_type=vt,
            length_m=getattr(args, "rv_length", None),
            gross_mass_kg=getattr(args, "rv_mass", None),
            license_class=getattr(args, "rv_license", None),
            is_tow=(True if getattr(args, "rv_tow", False) else None),
            vehicle_height_m=getattr(args, "rv_height", None),
            route_low_clearance=(True if getattr(args, "rv_low_clearance", False) else None),
            water_tank_l=getattr(args, "rv_water", None),
            people=args.people,
            days=days,
            battery_kwh=getattr(args, "rv_battery", None),
            use_ac=(True if getattr(args, "rv_ac", False) else
                    (False if getattr(args, "rv_no_ac", False) else None)),
            has_black_tank=({"yes": True, "no": False}.get(getattr(args, "rv_black_tank", None))),
            dump_plan=(True if getattr(args, "rv_dump_plan", False) else None),
            peak_season=(True if getattr(args, "rv_peak", False) else None),
            booked=(True if getattr(args, "rv_booked", False) else None),
        )
        rv_block["total_km"] = auto_total

    stay = stay_plan(args.people, profile, args.composition, args.lodging)
    _budget = budget_for(profile, days, args.people, args.lodging, args.food, stay=stay)
    # 预算分摊口径由 party 决定（不改动金额计算，只标注口径）
    _budget["split_mode"] = party.get("budget_mode", "")
    _budget["split_note"] = party.get("budget_note", "")
    # audience tips 叠加 party 安全/节奏要点（正交：只追加不覆盖）
    _aud_tips = list(aud_tips) + list(party.get("safety_focus", [])) + list(party.get("pacing_focus", []))
    return {
        "origin": args.origin or "未指定",
        "destinations": [t["name"] for t in targets],
        "days": days,
        "people": args.people,
        "composition": args.composition or "",
        "party": party,
        "style": profile.key,
        "style_label": profile.label,
        "intensity": profile.intensity,
        "tone": profile.tone,
        "gear_focus": profile.gear_focus,
        "plan": plan,
        "stay": {
            "rooms": stay.rooms,
            "room_types": stay.room_types,
            "rationale": stay.rationale,
            "tips": stay.tips,
            "room_note": party.get("room_note", ""),
        },
        "budget": _budget,
        "gear": gear_for(profile, season),
        "season": season,
        "special": special_advice(profile),
        "rv": rv_block,
        "moto": moto_block,
        "concert": concert_anchor(days, args.people) if profile.key == "concert" else None,
        "intents": intents,
        "prefs": prefs,
        "cold": cold,
        "audience": {
            "key": aud_key,
            "label": aud_label,
            "focus": aud_focus,
            "like": aud_like,
            "avoid": aud_avoid,
            "tips": aud_tips,
            "band": aud_band,
            "band_tips": aud_band_tips,
        },
    }


def _day_note(profile: StyleProfile, i: int, days: int) -> str:
    if i == 0:
        return "抵达后先安顿，轻活动开胃；别急着连打两个点"
    if i == days - 1 and days > 1:
        return "留足缓冲，别安排需要预约的项目；优先返程"
    notes = {
        "commando": "早出晚归，一天刷完核心清单，晚上回酒店泡脚",
        "leisure": "上午一个主点，下午一个副点，傍晚随便逛逛",
        "resort": "睡到自然醒，一个活动 + 一顿饭，把时间交给度假村",
        "relax": "不赶时间不打卡，睡到自然醒，想出门就出门，想待着就待着",
        "honeymoon": "看一次日出或日落，安排一顿有仪式感的晚餐",
        "roadtrip": "边开边停，服务区补给；日落前到观景点",
        "cycling": "按码表配速，午后注意返程，留出补水补给点",
        "hiking": "早出发避开日晒，中途设补给点，量力而行不硬撑",
        "moto": "控制节奏不赶夜路，傍晚前找好落脚点",
        "family": "上午户外、下午室内或回房午睡，20:00 前回住处",
        "couple": "留一个「散步时段」不发照片也不刷手机",
        "friends": "排满但留一顿夜宵时间，晚上才是主场",
        "camping": "白天轻徒步/玩水，傍晚扎营生火，夜观星河早休息",
        "rv": "上午慢开去下一营地，下午驻车玩水/煮饭，傍晚接水电",
        "budget": "早出晚归一票到底，白天步行串联，夜宿青旅省一笔",
        "photo": "赶日出与黄昏黄金光，正午转室内或补觉存卡",
        "study": "上午展馆/工坊，下午动手体验，晚上整理研学笔记",
        "silver": "九点出门不赶早，景点间隔留足休息，16 点前回住处",
        "ski": "上午缆车上山刷道，午后体力下降转初级道，傍晚泡汤",
        "island": "上午出海/浮潜，午后沙滩发呆，傍晚看日落",
        "ancient": "慢走青石板，茶馆听曲，摇橹船晃一圈，别赶场",
        "rail": "高铁说走就走，到站citywalk，傍晚高铁回城",
    }
    return notes.get(profile.key, "")


def _aud_nudge(aud_key: str) -> str:
    """按受众给每日追加一句『主动准备』的提醒, 用户不问也带着。"""
    m = {
        "male": "（男频提醒：留一段无计划窗口，随路遇调整，别被行程绑死）",
        "female": "（女频提醒：预留拍照黄金光与美食管段，独行注意安保与报位）",
        "family": "（亲子提醒：上午户外、午后回房午睡，随身包备药/防晒/换洗衣）",
        "elderly": "（长辈提醒：每 30-40min 坐下歇 5-10min，午休硬指标，16 点前回住处）",
    }
    return m.get(aud_key, "")


def main() -> int:
    ap = argparse.ArgumentParser(description="行程编排引擎")
    ap.add_argument("--from", dest="origin", help="出发地")
    ap.add_argument("--to", nargs="+", required=True, help="目的地(可多个)")
    ap.add_argument("--days", type=int, default=3, help="天数")
    ap.add_argument("--people", type=int, default=2, help="总人数")
    ap.add_argument("--composition", default="",
                    help="人员构成, 如 三口/二大一小/两大两小/情侣/朋友4人。影响房间分配")
    ap.add_argument("--party", default="",
                    help="出行陪伴结构(显式指定优先): solo/couple/friends-small/friends-large/family/group；未给则自动推断")
    ap.add_argument("--style", help="节奏画像 key")
    ap.add_argument("--hint", nargs="*", help="用户原话片段, 用于推断画像")
    ap.add_argument("--lodging", default="舒适", choices=list(LODGING))
    ap.add_argument("--food", default="舒适", choices=list(FOOD))
    ap.add_argument("--season", default="", help="季节: 春/夏/秋/冬")
    ap.add_argument("--budget", type=int, default=0, help="用户总预算(元), 用于与估算对比")
    ap.add_argument("--tag", nargs="*",
                    help="显式附加意图: hiking/sunrise/avoid_crowd/photo/foodie/culture")
    ap.add_argument("--no-fun", action="store_true",
                    help="不输出冷知识与趣味建议, 生成更紧凑严谨的行程")
    ap.add_argument("--audience", default=None,
                    choices=["male", "female", "family", "elderly", "general"],
                    help="受众维度: male/female/family/elderly/general(默认按人员构成自动推断)")
    # ── v0.1.1 摩旅模式：门禁自检输入。全部缺省为 None → 对应项走灰灯，不猜。──
    ap.add_argument("--moto-cc", dest="moto_cc", type=int, default=None,
                    help="摩托排量(cc)，用于按分档估算续航")
    ap.add_argument("--moto-range", dest="moto_range", type=float, default=None,
                    help="实际满油续航(km)，优先于排量估算")
    ap.add_argument("--moto-daily-km", dest="moto_daily_km", type=float, default=None,
                    help="单日计划里程(km)，缺省用摩旅画像自动值")
    ap.add_argument("--moto-license", dest="moto_license", default=None,
                    help="准驾车型 D/E/F；填了即视为已持有摩托车驾驶证")
    ap.add_argument("--moto-docs", dest="moto_docs", action="store_true",
                    help="已确认行驶证与交强险齐备")
    ap.add_argument("--moto-helmet", dest="moto_helmet", action="store_true",
                    help="已确认配备头盔")
    # ── v0.1.2 新增：绿荫优先 + 高速偏好 + 数据增强 ──
    ap.add_argument("--moto-shade-first", dest="moto_shade_first", action="store_true",
                    help="绿荫优先：线路推荐按林荫等级排序（暴晒规避优先于难度）")
    ap.add_argument("--moto-shade-min", dest="moto_shade_min", default=None,
                    choices=["高", "中", "低"],
                    help="最低绿荫等级，如 '中' 表示不要基本无遮蔽的线路")
    ap.add_argument("--moto-prefer-highway", dest="moto_prefer_highway",
                    action="store_true",
                    help="计划走高速：高速准入按红灯级判定，加油策略按服务区口径给")
    ap.add_argument("--moto-notes", dest="moto_notes", default=None,
                    help="补充信息 JSON 文件路径（检索回来的笔记，"
                         "每条需含 topic/content/source/date，自动标 third_party）")
    # ── v0.1.13 自驾/房车后勤：车型由用户声明，只按声明给后勤，不推荐车型 ──
    ap.add_argument("--vehicle-type", dest="vehicle_type", default=None,
                    choices=["sedan", "suv", "mpv", "rv"],
                    help="自驾车型（轿车/SUV/MPV/房车）；rv 画像缺省即房车。仅用于选择对应后勤，不做车型推荐")
    ap.add_argument("--rv-length", dest="rv_length", type=float, default=None,
                    help="车长(m)：≥6m 属黄牌需 B/A 照")
    ap.add_argument("--rv-mass", dest="rv_mass", type=float, default=None,
                    help="总质量(kg)：≥4500kg 属黄牌需 B/A 照")
    ap.add_argument("--rv-license", dest="rv_license", default=None,
                    help="驾照类型（C1/C2/B1/B2/A/C6）")
    ap.add_argument("--rv-tow", dest="rv_tow", action="store_true",
                    help="牵引旅居挂车（需 C6 准驾）")
    ap.add_argument("--rv-height", dest="rv_height", type=float, default=None,
                    help="实测整车高度(m，含空调外机/天线/天窗)：用于限高判定")
    ap.add_argument("--rv-low-clearance", dest="rv_low_clearance", action="store_true",
                    help="途经已知低限高路段（即便未给车高也按限高黄灯提示）")
    ap.add_argument("--rv-black-tank", dest="rv_black_tank", default=None, choices=["yes", "no"],
                    help="是否带车载黑水箱：yes=有(按房车排污指引)，no=无(床车/改装，轻量指引)")
    ap.add_argument("--rv-water", dest="rv_water", type=float, default=None,
                    help="净水箱容量(L)：估算补水节奏")
    ap.add_argument("--rv-battery", dest="rv_battery", type=float, default=None,
                    help="生活电池容量(度/kWh)：估算用电离网时长")
    ap.add_argument("--rv-ac", dest="rv_ac", action="store_true",
                    help="途中会开空调（用电升至8-15度/天，离网撑不过一夜）")
    ap.add_argument("--rv-no-ac", dest="rv_no_ac", action="store_true",
                    help="途中不开空调（基础用电2-3度/天）")
    ap.add_argument("--rv-dump-plan", dest="rv_dump_plan", action="store_true",
                    help="已规划合规排污点（黑水/灰水）")
    ap.add_argument("--rv-peak", dest="rv_peak", action="store_true",
                    help="旺季/法定假期出行（营地爆满需提前订）")
    ap.add_argument("--rv-booked", dest="rv_booked", action="store_true",
                    help="已预订/确认营位")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = ap.parse_args()

    result = build(args)
    profile = STYLE_PROFILES[result["style"]]  # 修复: 文本渲染需引用 profile
    # 预算核对: 用户给定预算 vs 估算总额
    if args.budget:
        b0 = result["budget"]
        diff = args.budget - b0["group_total"]
        b0["user_budget"] = args.budget
        b0["budget_diff"] = diff
        b0["budget_status"] = "within" if diff >= 0 else "over"
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    p = result
    print(f"═══ {p['origin']} → {' → '.join(p['destinations'])} ═══")
    print(f"天数 {p['days']} 天 | {p['people']} 人 | 节奏: {p['style_label']} (强度 {p['intensity']}/5)")
    print(f"语气: {' · '.join(p['tone'])}\n")
    for d in p["plan"]:
        active = d.get("active")
        line = f"── Day {d['day']} [{d['label']}] {d['city']} │ {d['spots']} 个点 │ 约 {d['total_hours']}h"
        if active:
            line += f" │ {active['label']} {active['km']}km"
        print(line)
        for s in d["slots"]:
            print(f"   {s['start']} {s['name']} · {s['spots']} 点 · {s['hours']}h(单点{s['per_spot']}h) — {s['note']}")
        if active:
            print(f"   {ACTIVE_ICON.get(profile.key,'🚗')} {active['note']}")
        print(f"   💡 {d['note']}\n")
    b = p["budget"]
    s = p["stay"]
    print("── 住宿安排 ──")
    print(f"   房间数: {s['rooms']} 间  |  建议: {'、'.join(s['room_types'])}")
    print(f"   理由: {s['rationale']}")
    for t in s["tips"]:
        print(f"   · {t}")
    print()
    print("── 预算估算 ──")
    print(f"   住宿按 {b['lodging_basis']}")
    for k, v in b["group"].items():
        print(f"   {k:4} 全团 ¥{v:>6}    人均 ¥{b['per_person'][k]:>5}")
    print(f"   合计: 人均 ¥{b['per_person_total']}    全团 ¥{b['group_total']}")
    if args.budget:
        status = "✅ 在预算内" if b.get("budget_status") == "within" else "⚠️ 超出预算"
        print(f"   用户预算 ¥{args.budget} | {status} ¥{abs(b.get('budget_diff', 0))}")
    print()

    # ── v0.1.1 摩旅模式：门禁自检输出 ──
    mb = result.get("moto")
    if mb:
        _ico = {"red": "⛔", "yellow": "⚠", "green": "✅", "grey": "◐"}
        print("── 摩旅自检（这辆车、这个人、这条路，合法且跑得下来吗）──")
        for c in mb["cards"]:
            print(f"   {_ico[c['light']]} {c['title']}: {c['detail'][:54]}")
            if c["title"].startswith("续航") and isinstance(c.get("items"), dict):
                it = c["items"]
                if it.get("theory_range_km"):
                    line = (f"      满油约 {it['theory_range_km']}km · "
                            f"安全续航 {it.get('safe_range_km')}km")
                    if it.get("expected_refuels"):
                        line += f" · 全程预计加油 {it['expected_refuels']} 次"
                    print(line)
        if mb.get("provinces"):
            print(f"   途经省份: {'、'.join(mb['provinces'])}")
        if mb.get("routes"):
            print("   参考线路:")
            for r in mb["routes"]:
                shade = f" · 绿荫 {r['shade']}" if r.get("shade") else ""
                print(f"     · {r['name']}（{r['group_label']} · {r['km']}km · "
                      f"{r['days']}天 · 难度 {r['level']}/5{shade}）")
                if r.get("summer_window") and p.get("season") == "夏":
                    print(f"       夏季建议: {r['summer_window']}")
        # v0.1.2 出行前待核实清单
        en = (mb.get("enrichment") or {})
        cl = en.get("checklist") or {}
        if cl.get("items"):
            print(f"── 出行前待核实清单（{cl.get('must_count', 0)} 项必须查）──")
            for it in cl["items"]:
                mark = "★" if it["must_check"] else " "
                print(f"   {mark} [{it['kind']}] {it['topic']}  → 检索: {it['query']}")
            print("   提示: 查不到就标 unknown，不要猜；社媒内容一律 third_party。")
        notes = [n for n in (en.get("notes") or []) if isinstance(n, dict) and "_errors" not in n]
        for n in notes:
            stale = " ⚠超过30天" if n.get("stale_warning") else ""
            print(f"   已核实 · {n['topic']}（{n['source']} {n['date']}"
                  f" · third_party{stale}）")
        print()

    # 多意图偏好块
    prefs = result.get("prefs") or []
    if prefs:
        print("── 出行偏好(由你的诉求生成) ──")
        for pr in prefs:
            print(f"   ★ {pr['主题']}: {pr['内容']}")
        print()

    # 受众维度(用户不问也先准备)
    aud = result.get("audience") or {}
    if aud.get("key") and aud["key"] != "general":
        print(f"── 受众专属准备 · {aud.get('label','')} ──")
        if aud.get("focus"):
            print("   关注: " + "；".join(aud["focus"]))
        if aud.get("like"):
            print("   偏好: " + "；".join(aud["like"]))
        if aud.get("avoid"):
            print("   避坑: " + "；".join(aud["avoid"]))
        if aud.get("band_tips"):
            print(f"   年龄段要点({aud.get('band','')}): " + "；".join(aud["band_tips"]))
        if aud.get("tips"):
            print("   贴士: " + "；".join(aud["tips"]))
        print()

    # 冷知识 + 趣味建议
    cold = result.get("cold") or []
    if cold:
        print("── 冷知识 · 趣味彩蛋 ──")
        for c in cold:
            if c.get("facts"):
                print(f"  ▣ {c['dest']} 冷知识:")
                for f in c["facts"]:
                    print(f"     · {f['标题']}: {f['内容']}")
            if c.get("fun"):
                print(f"  ✦ {c['dest']} 趣味建议:")
                for u in c["fun"]:
                    print(f"     - {u}")
        print()
    print("── 物料清单 ──")
    for cat, items in p["gear"].items():
        if items:
            print(f"   [{cat}] " + "、".join(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
