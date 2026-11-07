#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""融合专项断言（纯 stdlib）：目录层级/字段/版本/路由/离线数据/引用。任一失败 EXIT 1。"""
import json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "fixtures"
N = 0
FAIL = []

def ck(ok, label):
    global N
    N += 1
    if not ok: FAIL.append(label)
    print(("  PASS " if ok else "  FAIL ") + label)

def main():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    fm = dict()
    for line in text.split("---\n")[1].splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1); fm[k.strip()] = v.strip()

    print("[F1] 平台两级目录（S7 等价）")
    # 排除版本库、缓存、发布归档与独立专家包：这些都不是技能交付包内容。
    # expert/ 自带 .codebuddy-plugin/ 与 agents/ 子目录，其结构由
    # tools/verify_backup.py 单独校验，不适用技能包的两级目录断言。
    _VCS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "releases", "expert"}
    _walk = [(p, p.relative_to(ROOT)) for p in ROOT.rglob("*")
             if not any(part in _VCS for part in p.relative_to(ROOT).parts)]
    nested = [str(rel) for p, rel in _walk if p.is_dir() and len(rel.parts) > 1]
    deep = [str(rel) for p, rel in _walk if p.is_file() and len(rel.parts) > 2]
    ck(not nested, f"无二级嵌套目录（发现 {nested[:3]}）")
    ck(not deep, f"文件层级 <=2（发现 {deep[:3]}）")

    print("[F2] frontmatter 必填 5 项与版本四处一致")
    for k in ("description", "description_zh", "description_en", "version", "author"):
        ck(k in fm and bool(fm[k]), f"必填项 {k}")
    # 版本号现读现比，不写死：升版不再误报。
    _ver = fm.get("version", "")
    ck(("## v%s" % _ver) in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
       "CHANGELOG 含 v%s" % _ver)
    ck(("v%s" % _ver) in (ROOT / "QC_REPORT.md").read_text(encoding="utf-8"), "QC 报告版本同步")
    ck(('VER = "%s"' % _ver) in (ROOT / "tools/build_pack.py").read_text(encoding="utf-8"),
       "打包器版本同步")
    _desc = fm.get("description", "").strip('"')
    ck(len(_desc) <= 200, f"description <=200 字（实际 {len(_desc)}）")
    ck(fm.get("display_name_en", "").strip('"').__len__() <= 60, "display_name_en <=60 字符")

    print("[F3] 触发词与边界：按 description 实读基线，不锁死历史逐字")
    d = fm.get("description", "")
    for w in ("旅行规划", "行程规划", "旅游攻略", "周末去哪玩", "摩旅", "房车"):
        ck(w in d, f"触发词保留/新增 {w}")
    ck("不触发：" in d, "负向边界存在")
    ck((ROOT / "VERSION.json").is_file(), "版本真源存在")
    ck(json.loads((ROOT / "VERSION.json").read_text(encoding="utf-8"))["version"] == _ver,
       "版本真源与 SKILL.md 一致")

    print("[F3b] v0.2.22 新增机制入口齐备")
    for rel in ("scripts/worldstip.py", "scripts/intent_guard.py", "scripts/geo_extract.py",
                "scripts/history_query.py", "scripts/doctor.py", "tools/build_pack.py",
                "references/places_history.json", "scripts/render_booklet.py"):
        ck((ROOT / rel).is_file(), f"新增文件存在 {rel}")

    print("[F4] 双路由入口并存且行为不同")
    ck((SCRIPTS / "route.py").is_file(), "总路由 scripts/route.py 存在")
    ck((SCRIPTS / "motofun_route.py").is_file(), "摩旅路由 scripts/motofun_route.py 存在")
    r1 = subprocess.run([sys.executable, "-B", str(SCRIPTS / "route.py"),
                         "周末想去张家界爬山", "--json"], capture_output=True, text=True, timeout=60)
    ck(r1.returncode == 0, "总路由可跑 EXIT 0")
    r2 = subprocess.run([sys.executable, "-B", str(SCRIPTS / "motofun_route.py"),
                         "独库公路有什么好吃的", "--data-dir", str(FIXTURES),
                         "--offline", "--json"], capture_output=True, text=True, timeout=60)
    ck(r2.returncode == 0, "摩旅路由离线可跑 EXIT 0")
    try:
        j2 = json.loads(r2.stdout); ck(bool(j2.get("intent")) or "intent" in (j2.get("data") or {}), "摩旅路由返回 intent")
    except Exception:
        ck(False, "摩旅路由输出合法 JSON")

    print("[F5] 数据引擎离线取数与诚实降级")
    r3 = subprocess.run([sys.executable, "-B", str(SCRIPTS / "motofun.py"), "city",
                         "--name", "重庆", "--data-dir", str(FIXTURES), "--offline"],
                        capture_output=True, text=True, timeout=60)
    try:
        j3 = json.loads(r3.stdout); ck(j3["data"].get("found") is True, "重庆离线查得（非编造）")
    except Exception:
        ck(False, "city 输出合法 JSON")
    r4 = subprocess.run([sys.executable, "-B", str(SCRIPTS / "motofun.py"), "city",
                         "--name", "火星市", "--data-dir", str(FIXTURES), "--offline"],
                        capture_output=True, text=True, timeout=60)
    try:
        j4 = json.loads(r4.stdout); ck(j4["data"].get("found") is False, "未覆盖城市如实 found=false")
    except Exception:
        ck(False, "未覆盖输出合法 JSON")

    print("[F6] 数据纪律文件与夹具齐备")
    for rel in ("references/api-spec.md", "references/data-quality.md", "references/insights.md",
                "fixtures/moto_index.json", "fixtures/fun_data.json", "docs/FUSION.md",
                "tests/run_all.py", "QC_REPORT.md"):
        ck((ROOT / rel).is_file(), f"文件存在 {rel}")

    print("[F7] SKILL.md 反引号引用无真幽灵（按 scripts/ references/ 约定解析）")
    refs = set(re.findall(r"`([A-Za-z0-9_./\-]+\.(?:md|json|py))`", text))
    ghosts = []
    for r in sorted(refs):
        base = r.split("/")[-1]
        cands = [ROOT / r]
        if r.endswith(".py"): cands.append(SCRIPTS / base)
        elif r.endswith((".json", ".md")): cands.append(ROOT / "references" / base)
        RUNTIME = {"research.json", "plan.json", "transit.json", "weather.json", "manifest.json"}
        if not any(c.exists() for c in cands) and r not in RUNTIME:
            ghosts.append(r)
    ck(not ghosts, f"真幽灵引用 = 0（{ghosts[:5]}）；运行时产物名按约定排除")

    print(f"\nFUSED: {N - len(FAIL)} / {N} PASS, {len(FAIL)} FAIL")
    for f in FAIL: print("  FAILED:", f)
    return 1 if FAIL else 0

if __name__ == "__main__":
    raise SystemExit(main())
