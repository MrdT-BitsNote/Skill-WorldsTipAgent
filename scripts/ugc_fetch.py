#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时 UGC 软信息结构化工具（v0.1.0，学习 ycyliu 的小红书 UGC + 评论挖掘）。

本脚本不负责"联网抓取"（那由宿主 Agent 的 WebSearch / WebFetch，或 ycyliu 的
小红书 MCP 完成），它负责把抓回来的真实软信息**结构化 + 校验 + 落地**为
research.json 的 `ugc` 键，供 render_booklet._sec_ugc / _sec_pitfall 渲染。

为什么拆成两层（抓取 vs 结构化）：
- 小红书/点评的真实抓取依赖宿主环境（WebSearch / WebFetch / 小红书 MCP），
  本技能不硬依赖任何一个，避免"接了某个 MCP 才能用"。
- 结构化逻辑稳定可测，与抓取方式解耦；换数据源只改上游，不动渲染。

ugc 条目字段（与 ugc_badge.render_ugc 对齐）：
  src      可信度: 实测(亲历带图) > 平台(官方公示) > 博客(搜索/自媒体)
  chan     渠道: 小红书 / 大众点评 / 官方 / 搜索
  recency  时效: 近6月 > 近1年 > 更早
  is_comment 是否评论区口碑（评论 > 正文）
  kind     类型: 踩坑/避雷/避坑/价格陷阱/价格/体验/贴士
  where    地点
  text     内容

用法:
  # 1) 宿主 Agent 用 WebSearch/WebFetch/小红书 MCP 拉到原始观察，存为 research_raw.json（列表）
  # 2) 本脚本规整并写出 research.json
  python ugc_fetch.py --raw research_raw.json --out research.json
  # 追加合并到已有 research.json
  python ugc_fetch.py --raw more.json --merge research.json
"""
import argparse
import json
import sys

SRC_TIER = {"实测", "平台", "博客"}
CHAN_TIER = {"小红书", "大众点评", "官方", "搜索"}
RECENCY_TIER = {"近6月", "近1年", "更早"}
KIND_TIER = {"踩坑", "避雷", "避坑", "价格陷阱", "价格", "体验", "贴士"}


def _clean(v, default=""):
    v = (v or "").strip()
    return v or default


def normalize(item: dict) -> dict | None:
    """单条规整：补全默认字段、纠偏非法枚举；内容为空则返回 None（丢弃）。"""
    text = _clean(item.get("text"))
    if not text:
        return None
    src = _clean(item.get("src"), "博客")
    if src not in SRC_TIER:
        src = "博客"
    chan = _clean(item.get("chan"), "搜索")
    if chan not in CHAN_TIER:
        chan = "搜索"
    recency = _clean(item.get("recency"), "近1年")
    if recency not in RECENCY_TIER:
        recency = "近1年"
    kind = _clean(item.get("kind"), "体验")
    if kind not in KIND_TIER:
        kind = "体验"
    return {
        "src": src,
        "chan": chan,
        "recency": recency,
        "is_comment": bool(item.get("is_comment", False)),
        "kind": kind,
        "where": _clean(item.get("where"), "目的地"),
        "text": text,
    }


def structurize(raw: list) -> list:
    out = []
    for it in (raw or []):
        n = normalize(it)
        if n:
            out.append(n)
    return out


def load_research(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"ugc": []}
    except FileNotFoundError:
        return {"ugc": []}


def main() -> int:
    ap = argparse.ArgumentParser(description="实时 UGC 软信息结构化落地")
    ap.add_argument("--raw", required=True, help="原始观察 JSON（列表，或由 WebSearch/小红书 MCP 导出的条目）")
    ap.add_argument("--out", help="输出 research.json 路径")
    ap.add_argument("--merge", help="合并进已有 research.json（与 --out 二选一）")
    args = ap.parse_args()

    with open(args.raw, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get("ugc") or raw.get("items") or []
    ugc = structurize(raw)
    if not ugc:
        print("⚠️ 无有效 UGC 条目（每条需含非空 text），未写出。", file=sys.stderr)
        return 1

    if args.merge:
        research = load_research(args.merge)
        research["ugc"] = structurize(research.get("ugc") or []) + ugc
        out_path = args.merge
    else:
        out_path = args.out or "research.json"
        research = {"ugc": ugc}

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(research, f, ensure_ascii=False, indent=2)

    # 统计分层，便于核对
    by_kind = {}
    for u in ugc:
        by_kind[u["kind"]] = by_kind.get(u["kind"], 0) + 1
    print(f"✅ 已写出 {out_path}：本次规整 {len(ugc)} 条 UGC")
    print(f"   类型分布: {by_kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
