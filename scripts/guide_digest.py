# -*- coding: utf-8 -*-
"""
guide_digest.py — 攻略研读沉淀校验器（v0.1.28「攻略研读 → 数据沉淀」配套）。

职责：把宿主检索到的攻略**研读结论**（LLM 从攻略原文提取的结构化事实）落地为
`research.json` 的 `ugc` 条目，供渲染器写进小册子「攻略核验 · 数据补充」子块。

纪律（对应 SKILL.md「攻略检索模式 · 研读沉淀」与「链接、日期与断言纪律」）：
- **只取三元组，不照搬原文**：输入必须是「结论 + 来源 + 核验日期」的结构化事实，
  且研读时已转写为可执行项（具体名字 + 数字 + 时间窗）；本脚本不抓取、不保存原文。
- **缺三元组即拒**：fact / source / verified_on / confidence 缺任一 → 拒绝进册
  （灰灯「待核实」不进正文结论，与既有纪律一致）。
- **同事实多来源合并升级**：同一结论 ≥2 个独立来源 → confidence 升为 verified
  （渲染徽章「多源印证」）；单源标「个别反馈」。
- **日期拒未来**；verified_on 需为 YYYY-MM-DD。
- **时效分级**：volatile 类（票务/排队/衔接）>30 天、体验类（餐饮/避雷/机位/贴士）>90 天
  → 输出 needs_recheck 标记，渲染端挂「需出行前复核」。
- **category → kind 映射**：输出兼容既有 ugc 结构（kind/where/text/src/source/recency/
  verified_on/confidence），并附 category 供新渲染块分组；旧渲染器忽略新增字段。

用法：
    python scripts/guide_digest.py facts.json                  #  stdout 输出 ugc JSON 数组
    python scripts/guide_digest.py facts.json --merge research.json  # 合并写回 research.json
    python scripts/guide_digest.py facts.json --strict         # 有拒绝即退出码 1
"""
import json
import re
import sys
from datetime import date, datetime

# --- 词表 -------------------------------------------------------------------
CATEGORY_KIND = {
    "ticket": "价格",   # 票价 / 开放时间 / 预约规则
    "transit": "贴士",  # 交通衔接 / 末班车 / 接驳
    "queue": "体验",    # 排队 / 分时预约 / 最佳时段
    "food": "体验",     # 餐饮 / 小吃
    "pitfall": "踩坑",  # 避雷 / 踩坑
    "photo": "体验",    # 机位 / 拍摄
    "tip": "贴士",      # 其他贴士
}
CATEGORY_ZH = {
    "ticket": "票务与预约", "transit": "交通衔接", "queue": "排队与时段",
    "food": "餐饮", "pitfall": "避雷踩坑", "photo": "机位与拍摄", "tip": "实用贴士",
}
VOLATILE_CATS = {"ticket", "queue", "transit"}   # >30 天需复核
EXPERIENCE_CATS = {"food", "pitfall", "photo", "tip"}  # >90 天需复核
CONFIDENCE_SRC = {  # confidence → (src, confidence) 落地值
    "official": ("官方", "官方"),
    "verified": ("检索", "检索"),
    "single": ("检索", "检索"),
}
SOURCE_TYPES = ("official", "ugc_qa", "ugc_review", "ugc_social", "ugc_video", "other")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _norm_fact(text):
    """事实归一化（去重键）：小写、去空白与常见标点。"""
    return re.sub(r"[\s，。、；：？！,.;:?!]+", "", str(text).lower())


def _parse_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def validate_fact(e, idx):
    """校验单条研读结论，返回错误列表。"""
    errs = []
    if not isinstance(e, dict):
        return ["条目 %d：不是对象" % idx]
    fact = e.get("fact")
    if not isinstance(fact, str) or not fact.strip():
        errs.append("条目 %d：缺 fact（一句话结论）" % idx)
    elif len(fact) > 160:
        errs.append("条目 %d：fact 超 160 字（应是一句话结论，不是原文段落）" % idx)
    if e.get("category") not in CATEGORY_KIND:
        errs.append("条目 %d：category 需为 %s" % (idx, "/".join(CATEGORY_KIND)))
    for k in ("source", "verified_on", "confidence"):
        v = e.get(k)
        if not isinstance(v, str) or not v.strip():
            errs.append("条目 %d：缺 %s（三元组必填，缺即灰灯不进册）" % (idx, k))
    if e.get("confidence") not in CONFIDENCE_SRC:
        errs.append("条目 %d：confidence 需为 official/verified/single"
                    "（unknown 未核验，拒绝进册）" % idx)
    if e.get("source_type", "other") not in SOURCE_TYPES:
        errs.append("条目 %d：source_type 非法" % idx)
    d = _parse_date(e.get("verified_on"))
    if isinstance(e.get("verified_on"), str) and e["verified_on"].strip() and d is None:
        errs.append("条目 %d：verified_on 需为 YYYY-MM-DD" % idx)
    if d and d > date.today():
        errs.append("条目 %d：verified_on 是未来日期（拒绝）" % idx)
    return errs


def merge_facts(valid):
    """按归一化 fact 合并：同事实多来源 → verified/多源印证；同事实同来源 → 去重。"""
    groups = {}
    order = []
    for e in valid:
        key = _norm_fact(e["fact"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(e)
    merged = []
    for key in order:
        items = groups[key]
        # 同来源去重（按 source 名称）
        seen_src = set()
        uniq = []
        for it in items:
            s = it["source"].strip()
            if s in seen_src:
                continue
            seen_src.add(s)
            uniq.append(it)
        # 置信度取最高（official > verified > single）
        rank = {"official": 3, "verified": 2, "single": 1}
        best = max(uniq, key=lambda x: rank.get(x["confidence"], 0))
        conf = best["confidence"]
        if len(uniq) >= 2 and conf != "official":
            conf = "verified"  # 多源印证升级
        latest = max(_parse_date(x["verified_on"]) for x in uniq)
        cat = best.get("category", "tip")
        src, conf_out = CONFIDENCE_SRC[conf]
        merged.append({
            "kind": CATEGORY_KIND.get(cat, "贴士"),
            "where": best.get("spot") or best.get("where") or "全程",
            "text": best["fact"].strip(),
            "src": src,
            "source": "；".join(x["source"].strip() for x in uniq),
            "sources": [x["source"].strip() for x in uniq],
            "multi": len(uniq) >= 2,
            "recency": _recency(latest),
            "verified_on": latest.isoformat(),
            "confidence": conf_out,
            "category": cat,
            "needs_recheck": _needs_recheck(latest, cat),
        })
    return merged


def _recency(d):
    if not d:
        return "更早"
    days = (date.today() - d).days
    if days <= 183:
        return "近6月"
    if days <= 365:
        return "近1年"
    return "更早"


def _needs_recheck(d, cat):
    if not d:
        return True
    days = (date.today() - d).days
    limit = 30 if cat in VOLATILE_CATS else 90
    return days > limit


def load_facts(path):
    raw = sys.stdin.read() if path == "-" else open(path, "r", encoding="utf-8").read()
    data = json.loads(raw)
    if isinstance(data, dict) and "facts" in data:
        data = data["facts"]
    if not isinstance(data, list):
        raise ValueError("输入需为 JSON 数组（或含 facts 数组的对象）")
    return data


def main(argv):
    positional = []
    merge_path = None
    skip_next = False
    for i, a in enumerate(argv[1:]):
        if skip_next:
            skip_next = False
            continue
        if a == "--merge":
            if i + 2 >= len(argv):
                sys.stderr.write("--merge 需要 research.json 路径\n")
                return 2
            merge_path = argv[i + 2]
            skip_next = True
            continue
        if a.startswith("--"):
            continue
        positional.append(a)
    strict = "--strict" in argv
    if len(positional) != 1:
        sys.stderr.write("usage: guide_digest.py <facts.json|-> [--merge research.json] [--strict]\n")
        return 2
    try:
        raw_facts = load_facts(positional[0])
    except Exception as ex:
        sys.stderr.write("读取失败：%s\n" % ex)
        return 2
    errs = []
    valid = []
    for i, e in enumerate(raw_facts, 1):
        es = validate_fact(e, i)
        if es:
            errs.extend(es)
        else:
            valid.append(e)
    for line in errs:
        sys.stderr.write("[拒绝] %s\n" % line)
    ugc = merge_facts(valid)
    if not ugc:
        sys.stderr.write("无有效沉淀条目（%d 条输入全部被拒或为空）\n" % len(raw_facts))
        return 1 if strict else 0
    if merge_path:
        try:
            research = json.load(open(merge_path, encoding="utf-8"))
        except (OSError, ValueError):
            research = {}
        existing = research.get("ugc") or []
        # 按归一化 text 与既有条目去重后合并
        seen = {_norm_fact(x.get("text", "")) for x in existing if isinstance(x, dict)}
        research["ugc"] = existing + [u for u in ugc if _norm_fact(u["text"]) not in seen]
        with open(merge_path, "w", encoding="utf-8") as f:
            json.dump(research, f, ensure_ascii=False, indent=2)
        sys.stderr.write("已合并写回 %s（ugc 共 %d 条）\n" % (merge_path, len(research["ugc"])))
    else:
        print(json.dumps(ugc, ensure_ascii=False, indent=2))
    stale = sum(1 for u in ugc if u["needs_recheck"])
    multi = sum(1 for u in ugc if u["multi"])
    sys.stderr.write("沉淀 %d 条（输入 %d，拒绝 %d，多源印证 %d，需复核 %d）\n" % (
        len(ugc), len(raw_facts), len(raw_facts) - len(valid), multi, stale))
    return 1 if (strict and errs) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
