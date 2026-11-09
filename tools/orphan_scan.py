#!/usr/bin/env python3
"""orphan_scan.py — 包内「脚本可达性」与「数据消费者」扫描。

回答两个问题：
  1. 包内每个 scripts/*.py 是否还有人调用？
  2. 包内每份数据文件是否还有人读？

## 脚本三级判据
  ENTRY   入口脚本（worldstip.py 总入口 / doctor 等维护入口）
  CODE    从入口经 import / `xxx.py` / subprocess 字符串可达
  DOC     在 shipped doc 中以 `scripts/xxx.py` **可执行形态**被点名（模型会跑）
  MENTION 只在文档里出现文件名，但不是可执行形态（资源表罗列）—— 弱引用，需补命令或补调用
  ORPHAN  既无调用方也无文档指令 —— 包内垃圾，必须接线或剔除

## 数据判据
  CODE    有 shipped 且可达的脚本字面引用（最强）
  DOC     有 shipped doc 的「读法」行（同句含 读/加载/检索/查/参考/清单 等动词）
  WEAK    只在资源清单里被罗列，无读法指令
  ORPHAN  全文无任何提及
  传递降级：仅被 ORPHAN/MENTION 脚本引用的数据，降为 WEAK。

用法：
  python tools/orphan_scan.py --root <目录> [--json] [--strict]
  --strict  存在 ORPHAN 时退出码 1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict, deque

BASE_ENTRIES = ["worldstip.py"]
MAINT_ENTRIES = ["doctor.py", "sync_check.py", "volatile_verify.py"]
# 仓库内统一回归入口（不随包分发）：它 subprocess 拉起各个 test_*.py
EXTRA_ENTRY_FILES = ["tests/run_all.py"]

SCRIPT_RE = re.compile(r"scripts/([A-Za-z0-9_]+)\.py")
# 数据「读法」动词：同句出现才认作文档级消费
READ_VERB_RE = re.compile(r"读取|读入|加载|载入|检索|查询|查阅|参考|调取|消费|清单|检索库|load|read")
DATA_EXT = (".json", ".csv", ".tsv", ".geojson")


def _stem(p: str) -> str:
    return os.path.splitext(os.path.basename(p))[0]


def _ref_pattern(stem: str):
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(stem) + r"(?![A-Za-z0-9_])")


def load_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def collect_scripts(root: str):
    sd = os.path.join(root, "scripts")
    if not os.path.isdir(sd):
        return []
    return sorted(f for f in os.listdir(sd) if f.endswith(".py"))


def collect_docs(root: str):
    out = []
    skill = os.path.join(root, "SKILL.md")
    if os.path.isfile(skill):
        out.append(skill)
    dd = os.path.join(root, "docs")
    if os.path.isdir(dd):
        for f in sorted(os.listdir(dd)):
            if f.endswith(".md"):
                out.append(os.path.join(dd, f))
    return out


def build_graph(root: str, scripts):
    texts = {s: load_text(os.path.join(root, "scripts", s)) for s in scripts}
    graph = defaultdict(set)
    for a in scripts:
        ta = texts[a]
        for b in scripts:
            if a == b:
                continue
            if _ref_pattern(_stem(b)).search(ta):
                graph[a].add(b)
    return graph, texts


def doc_calls(root: str, scripts):
    """返回 (runnable, mention)：可执行形态 / 仅罗列。"""
    runnable, mention = defaultdict(list), defaultdict(list)
    for p in collect_docs(root):
        rel = os.path.relpath(p, root).replace("\\", "/")
        txt = load_text(p)
        hit = set()
        for m in SCRIPT_RE.finditer(txt):
            name = m.group(1) + ".py"
            if name in scripts:
                if rel not in runnable[name]:
                    runnable[name].append(rel)
                hit.add(name)
        for s in scripts:
            if s not in hit and s in txt:
                if rel not in mention[s]:
                    mention[s].append(rel)
    return runnable, mention


def reachable(scripts, graph, seeds):
    seen, q = set(), deque(s for s in seeds if s in scripts)
    seen.update(q)
    while q:
        cur = q.popleft()
        for nxt in graph.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return seen


def extra_seed_scripts(root: str, scripts):
    """tests/run_all.py 等仓内入口引用的脚本，算作 CODE 可达。

    同时支持 glob 发现（run_all.py 用 `test_*.py` 前缀+后缀动态枚举）。
    """
    import fnmatch
    hit = set()
    for rel in EXTRA_ENTRY_FILES:
        p = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(p):
            continue
        txt = load_text(p)
        for s in scripts:
            if s in txt or _ref_pattern(_stem(s)).search(txt):
                hit.add(s)
        # glob 形态：文中出现 "test_*.py" / "*.py" 之类模式
        for m in re.finditer(r"([A-Za-z0-9_*]+\.py)", txt):
            pat = m.group(1)
            if "*" not in pat:
                continue
            if pat == "*.py":
                continue
            hit.update(s for s in scripts if fnmatch.fnmatch(s, pat))
    return hit


def data_consumers(root: str, scripts, texts, doc_paths, good_scripts):
    rows = []
    dirs = []
    for cand in ("references", "data", "assets/data"):
        d = os.path.join(root, *cand.split("/"))
        if os.path.isdir(d):
            dirs.append(d)
    doc_text = {os.path.relpath(p, root).replace("\\", "/"): load_text(p) for p in doc_paths}
    for d in dirs:
        for dirpath, _dn, filenames in os.walk(d):
            for f in filenames:
                if not f.endswith(DATA_EXT):
                    continue
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, root).replace("\\", "/")
                users = sorted(s for s in scripts if f in texts[s])
                good_users = [s for s in users if s in good_scripts]
                docs_read, docs_mention = [], []
                for drel, txt in doc_text.items():
                    if f not in txt:
                        continue
                    ok = False
                    for line in txt.splitlines():
                        if f in line and READ_VERB_RE.search(line):
                            ok = True
                            break
                    (docs_read if ok else docs_mention).append(drel)
                if good_users:
                    status = "CODE"
                elif users:
                    status = "STALE"          # 只有不可达脚本在引用
                elif docs_read:
                    status = "DOC"
                elif docs_mention:
                    status = "WEAK"
                else:
                    status = "ORPHAN"
                rows.append({
                    "file": rel,
                    "bytes": os.path.getsize(full),
                    "scripts": users,
                    "scripts_reachable": good_users,
                    "docs_read": sorted(docs_read),
                    "docs_mention": sorted(docs_mention),
                    "status": status,
                })
    return rows


def dangling_refs(root: str):
    """文档里点名的「实体路径」是否真的存在（反向检查：无实体支撑的调用方）。

    只查 scripts/ docs/ references/ tests/ 四个前缀，且忽略目录形态（x/）。
    """
    import glob as _glob
    pat = re.compile(r"(?:^|[\s`'\"(（\[])((?:scripts|docs|references|tests)/[A-Za-z0-9_.\-]+\.(?:py|md|json))")
    # 已声明「不随包 / 仅源码仓库」的行不算悬空（诚实标注即合规）
    external = re.compile(r"源码仓库|源码树|仅开发|不随包|包内不含|不进包")
    seen = {}
    for p in collect_docs(root):
        rel = os.path.relpath(p, root).replace("\\", "/")
        if "CHANGELOG" in rel.upper():
            continue  # 往期条目描述历史版本当时的文件，不参与对账
        for i, line in enumerate(load_text(p).splitlines(), 1):
            for m in pat.finditer(line):
                ref = m.group(1)
                full = os.path.join(root, *ref.split("/"))
                if os.path.isfile(full):
                    continue
                if external.search(line):
                    continue
                seen.setdefault(ref, []).append(f"{rel}:{i}")
    return [{"ref": k, "where": v} for k, v in sorted(seen.items())]


def scan(root: str):
    root = os.path.abspath(root)
    scripts = collect_scripts(root)
    if not scripts:
        return {"root": root, "error": "no scripts/ directory"}
    graph, texts = build_graph(root, scripts)
    seeds = [s for s in BASE_ENTRIES + MAINT_ENTRIES if s in scripts]
    via_tests = extra_seed_scripts(root, scripts)
    code_reach = reachable(scripts, graph, seeds) | via_tests
    runnable, mention = doc_calls(root, scripts)

    rows = []
    for s in scripts:
        if s in seeds:
            status, via = "ENTRY", ["ENTRY"]
        elif s in via_tests:
            callers = sorted(a for a in scripts if s in graph.get(a, ()))
            status, via = "CODE", ["TEST:tests/run_all.py"]
        elif s in code_reach:
            callers = sorted(a for a in scripts if s in graph.get(a, ()))
            status, via = "CODE", ["CODE:" + ",".join(callers[:6])]
        elif s in runnable:
            status, via = "DOC", ["DOC:" + ",".join(runnable[s][:3])]
        elif s in mention:
            status, via = "MENTION", ["MENTION:" + ",".join(mention[s][:3])]
        else:
            status, via = "ORPHAN", []
        rows.append({
            "script": s,
            "lines": texts[s].count("\n") + 1,
            "callers": sorted(a for a in scripts if s in graph.get(a, ())),
            "via": via,
            "status": status,
        })

    good = {r["script"] for r in rows if r["status"] in ("ENTRY", "CODE", "DOC")}
    data = data_consumers(root, scripts, texts, collect_docs(root), good)
    dangling = dangling_refs(root)
    return {
        "root": root,
        "dangling": dangling,
        "scripts_total": len(scripts),
        "entries": seeds,
        "table": rows,
        "data": data,
        "summary": {
            "scripts_entry": sum(1 for r in rows if r["status"] == "ENTRY"),
            "scripts_code": sum(1 for r in rows if r["status"] == "CODE"),
            "scripts_doc": sum(1 for r in rows if r["status"] == "DOC"),
            "scripts_mention": sum(1 for r in rows if r["status"] == "MENTION"),
            "scripts_orphan": sum(1 for r in rows if r["status"] == "ORPHAN"),
            "data_total": len(data),
            "data_code": sum(1 for d in data if d["status"] == "CODE"),
            "data_doc": sum(1 for d in data if d["status"] == "DOC"),
            "data_stale": sum(1 for d in data if d["status"] == "STALE"),
            "data_weak": sum(1 for d in data if d["status"] == "WEAK"),
            "data_orphan": sum(1 for d in data if d["status"] == "ORPHAN"),
            "dangling": len(dangling),
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    rep = scan(args.root)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        if "error" in rep:
            print("ERROR: " + rep["error"])
            return 2
        print(f"ROOT {rep['root']}")
        print(f"入口: {', '.join(rep['entries'])}")
        print(f"脚本 {rep['scripts_total']} 个 / 数据 {rep['summary']['data_total']} 份")
        print("-" * 74)
        for tag in ("ORPHAN", "MENTION"):
            for r in rep["table"]:
                if r["status"] == tag:
                    print(f"  {tag:8}{r['script']:<26} {r['lines']:>5} 行  {r['via'][0][:44] if r['via'] else '无任何引用'}")
        for d in rep.get("dangling") or []:
            print(f"  DANGLING{d['ref']:<38} {d['where'][0]}")
        for tag in ("ORPHAN", "WEAK", "STALE"):
            for d in rep["data"]:
                if d["status"] == tag:
                    print(f"  {tag:8}{d['file']:<38} {d['bytes']/1024:>7.1f}K")
        print("-" * 74)
        s = rep["summary"]
        print(f"脚本: ENTRY {s['scripts_entry']} / CODE {s['scripts_code']} / DOC {s['scripts_doc']}"
              f" / MENTION {s['scripts_mention']} / ORPHAN {s['scripts_orphan']}")
        print(f"数据: CODE {s['data_code']} / DOC {s['data_doc']} / STALE {s['data_stale']}"
              f" / WEAK {s['data_weak']} / ORPHAN {s['data_orphan']}")
        bad = s["scripts_orphan"] + s["data_orphan"] + s["dangling"]
        warnc = s["scripts_mention"] + s["data_weak"] + s["data_stale"]
        verdict = "PASS" if bad == 0 and warnc == 0 else ("WARN" if bad == 0 else "FAIL")
        print(f"ORPHAN_SCAN: {verdict}")
        return 0 if (verdict != "FAIL" or not args.strict) else 1
    s = rep.get("summary", {})
    bad = s.get("scripts_orphan", 1) + s.get("data_orphan", 1)
    return 0 if (bad == 0 or not args.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
