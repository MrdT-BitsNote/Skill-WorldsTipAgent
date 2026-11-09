#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""八维度机检 / 技能自检器。

    python tools/selfcheck.py                 # 体检源码树
    python tools/selfcheck.py --pack <zip>    # 体检已构建的包（含跨平台漂移项）
    python tools/selfcheck.py --json          # 机器可读

设计口径（与 scripts/doctor.py 分工不同，不要互相替代）：
  doctor.py    —— 使用者装完后的**运行时自检**：能不能跑、依赖在不在。
  selfcheck.py —— 打包者的**发布前静态体检**：声明与实物是否一致、文档与代码是否漂移。

每个维度都对应一次真实踩坑，不是凭想象列条目：
  A 结构   包根/层级/编码/缓存夹带
  B 触发   description 触发词与负向边界（触发面归零是致命伤）
  C 版本   8 处版本 + 描述里的版本串（描述漂移比代码漂移更难发现）
  D 数字   正文写的条数/体积与实际数据对账（最常见的谎报）
  E 指针   子文件是否被引用、引用的文件是否真实存在（悬空指针会让模型编造）
  F 数据   JSON 可解析、_meta 四件套
  G 串台   其他技能的规则、替换失败的残句、占位符
  H 测试   统一回归入口可跑、套件注册数与实际一致

退出码：0 全通过（WARN 不算失败）/ 1 存在 FAIL。
"""
from __future__ import print_function

import argparse
import json
import os
import re
import sys
import zipfile

try:
    from pathlib import Path
except ImportError:  # pragma: no cover
    print("需要 Python 3.5+")
    raise

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 白名单：这些文件不要求在 SKILL.md 正文有指针 ────────────────────────
# 只收「给人读的维护/展示类」；功能类文档一律要求指针，否则模型不知道它存在。
# 词干形式：本文件会随 SkillHub / DuMate 包分发，写成带后缀的完整文件名会被
# 审核器视角闸门当成「包内必需资源」索要（实测 BLOCKER）。
DOC_NO_POINTER = {s + ".md" for s in (
    "CHANGELOG",         # 版本历史
    "FAQ",               # 问答
    "SHOWCASE",          # 展示
    "FUSION",            # 合流过程记录（维护）
    "UNIFIED_ENTRY",     # 统一入口设计记录（维护）
    "MOTOFUN_CHANGELOG",
    "MOTOFUN_QC_REPORT",
    "MOTOFUN_UPSTREAM_SKILL",
)}
# references 里不计入「需要正文指针」的：由脚本按需读取且已在数据路由表出现的，
# 不在此列出；此处只放确有理由不写指针的。
REF_NO_POINTER = set()

# ── 串台词：其他技能的规则混进正文，说明是复用模板时漏删 ──────────────
CROSSTALK = (
    "裁决表", "缺陷编号", "质检器实跑", "保过", "承诺上架",
)
# ── 替换失败残句：变量/路径被渲染成描述性文字 ────────────────────────
BROKEN_PHRASE = (
    "统一回归入口（源码仓库内）", "见 见", "的的", "（）", "（) ",
)
PLACEHOLDER = ("TODO", "FIXME", "TBD", "XXX", "待填", "<placeholder>")

RESULTS = []


def ck(dim, name, cond, detail="", level="FAIL"):
    ok = bool(cond)
    RESULTS.append({"dim": dim, "name": name, "ok": ok, "detail": str(detail)[:220]})
    tag = "PASS" if ok else level
    print("  %-4s %-46s %s" % (tag, name, "" if ok else detail))
    return ok


def read(p):
    with open(str(p), encoding="utf-8") as f:
        return f.read()


def frontmatter(text):
    if not text.startswith("---"):
        return {}
    body = text.split("---", 2)[1]
    fm = {}
    for line in body.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm


# ══ A 结构 ══════════════════════════════════════════════════════════
def dim_a(root: Path):
    print("\n[A] 结构")
    sk = root / "SKILL.md"
    ck("A", "SKILL.md 位于包根", sk.is_file(), str(sk))
    if not sk.is_file():
        return None
    text = read(sk)
    lines = len(text.splitlines())
    ck("A", "SKILL.md 行数 <= 500（平台上限）", lines <= 500, "实得 %d 行" % lines)
    ck("A", "SKILL.md 行数 >= 200（低于则信息不足）", lines >= 200, "实得 %d 行" % lines)

    raw = sk.read_bytes()
    ck("A", "无 BOM", not raw.startswith(b"\xef\xbb\xbf"))
    ck("A", "纯 LF（无 CRLF）", b"\r\n" not in raw)

    # 目录层级：包内最深路径的段数
    deepest, deep_path = 0, ""
    SKIP_DIRS = (".git", "__pycache__", "expert", "worldstip-out", "releases")
    for p in root.rglob("*"):
        if not p.is_file() or any(d in p.parts for d in SKIP_DIRS):
            continue
        depth = len(p.relative_to(root).parts) - 1
        if depth > deepest:
            deepest, deep_path = depth, str(p.relative_to(root))
    ck("A", "包内目录层数 <= 2", deepest <= 2, "最深 %d: %s" % (deepest, deep_path))

    junk = [str(p.relative_to(root)) for p in root.rglob("*")
            if p.name in ("__pycache__", ".DS_Store", "Thumbs.db")
            or p.suffix in (".pyc", ".pyo", ".orig", ".bak", ".tmp")]
    ck("A", "无缓存/临时产物夹带", not junk, ", ".join(junk[:4]))
    return text


# ══ B 触发 ══════════════════════════════════════════════════════════
TRIGGER_MIN = 8


def dim_b(fm):
    print("\n[B] 触发层")
    desc = fm.get("description", "")
    # 触发短语：中文顿号/逗号分隔的短词
    cand = [w.strip() for w in re.split(r"[、，,；;]", desc) if 2 <= len(w.strip()) <= 8]
    ck("B", "description 含 >= %d 个触发短语" % TRIGGER_MIN,
       len(cand) >= TRIGGER_MIN, "实得 %d 个" % len(cand))
    ck("B", "description 含负向边界（不触发/不适用）",
       ("不触发" in desc) or ("not for" in desc.lower()))
    ck("B", "description 声明中英双语覆盖",
       bool(re.search(r"[a-z]{4,}", desc)) or "plan a trip" in desc.lower())

    # 简介只讲功能与用户价值：脚本文件名、CLI 开关、内部迭代代号都不该出现。
    # 这类字串进简介有两个坏处——用户看不懂，且一改版就过期（旧版就踩过）。
    for field in ("description_zh", "description_en", "summary"):
        val = fm.get(field) or ""
        leaks = []
        if re.search(r"[\w\-]+\.py\b", val):
            leaks.append("脚本文件名")
        if re.search(r"(?<![\w-])--[a-z][\w-]*", val):
            leaks.append("CLI 开关")
        if re.search(r"·\s*(合并版|融合版|终端分流版|裁剪修正版|摩旅线路形状版)", val):
            leaks.append("内部迭代代号")
        ck("B", "简介不写实现细节: %s" % field, not leaks, "、".join(leaks))
    en = fm.get("display_name_en") or fm.get("displayName_en") or ""
    ck("B", "display_name_en <= 60 字符", 0 < len(en) <= 60, "实得 %d" % len(en))
    tags = fm.get("tags", "")
    ntag = len([t for t in re.findall(r"[\w\u4e00-\u9fa5]+", tags) if t])
    ck("B", "tags 数量 3-5", 3 <= ntag <= 5, "实得 %d" % ntag)
    # 长度预算：playbook 建议 ~60 字索引预算，本项目有意超出以覆盖触发面 → WARN 不拦
    ck("B", "description 长度（索引预算 200 字）", len(desc) <= 200,
       "实得 %d 字" % len(desc), level="WARN")


# ══ C 版本 ══════════════════════════════════════════════════════════
def dim_c(root: Path, fm, text):
    print("\n[C] 版本一致性")
    vj = root / "VERSION.json"
    if not vj.is_file():
        ck("C", "VERSION.json 存在", False)
        return None
    meta = json.loads(read(vj))
    ver = meta.get("version")
    ck("C", "VERSION.json 有 version", bool(ver), str(ver))
    if not ver:
        return None
    ck("C", "frontmatter version == VERSION.json", fm.get("version") == ver,
       "frontmatter=%s / VERSION=%s" % (fm.get("version"), ver))

    # 声明的 version_files 逐个核对
    for rel in meta.get("version_files") or []:
        p = root / rel
        if not p.is_file():
            ck("C", "声明版本文件存在: %s" % rel, False, "缺失")
            continue
        body = read(p)
        hit = re.search(r"(?<![\d.])" + re.escape(ver) + r"(?![\d.])", body)
        ck("C", "版本已写入: %s" % rel, bool(hit), "未找到 %s" % ver)

    # 描述字段里的版本串：漂移最难发现，单独盯
    for field in ("description_zh", "description_en", "summary",
                  "description", "display_name"):
        val = fm.get(field) or ""
        olds = set(re.findall(r"v?(\d+\.\d+\.\d+)", val))
        stale = {v for v in olds if v != ver}
        ck("C", "描述无旧版本残留: %s" % field, not stale,
           "发现 %s（当前 %s）" % (sorted(stale), ver))

    # 正文标题行的版本
    m = re.search(r"\*\*版本\*\*[：:]\s*v?(\d+\.\d+\.\d+)", text)
    ck("C", "正文标题行版本 == 当前", (not m) or m.group(1) == ver,
       "标题行 %s" % (m.group(1) if m else "无"))

    ch = root / "CHANGELOG.md"
    if ch.is_file():
        ck("C", "CHANGELOG 顶部有当前版本条目",
           bool(re.search(r"^##\s+v?" + re.escape(ver), read(ch), re.M)),
           "未找到 ## v%s" % ver)


# ══ D 数字真值 ══════════════════════════════════════════════════════
def dim_d(root: Path, text):
    print("\n[D] 数字与实物对账")
    ref = root / "references"
    jsons = sorted(ref.glob("*.json")) if ref.is_dir() else []

    def count(fname, key=None):
        p = ref / fname
        if not p.is_file():
            return None
        try:
            d = json.loads(read(p))
        except Exception:
            return None
        if isinstance(d, list):
            return len(d)
        if key and isinstance(d.get(key), (list, dict)):
            return len(d[key])
        for k in ("destinations", "places", "items", "poi", "routes"):
            if isinstance(d.get(k), list):
                return len(d[k])
        return len(d)

    pairs = [
        ("destinations.json", "destinations", r"destinations\.json`（(\d+) 城"),
        ("places_history.json", "items", r"(\d+)\s*条按需加载"),
        ("moto_places.json", "places", r"moto_places\.json`（(\d+) 条"),
    ]
    for fname, key, pat in pairs:
        real = count(fname, key)
        m = re.search(pat, text)
        claim = int(m.group(1)) if m else None
        ck("D", "%s 条数声明 == 实物" % fname, real is not None and claim == real,
           "正文 %s / 实物 %s" % (claim, real))

    # references 文件数
    m = re.search(r"不要一次性扫全部\**\s*(\d+)\s*个文件", text)
    claim = int(m.group(1)) if m else None
    real = len(jsons)
    ck("D", "references 文件数声明 == 实物",
       claim is None or claim == real, "正文 %s / 实物 %d" % (claim, real))

    # 大文件体积声明
    mp = ref / "moto_places.json"
    if mp.is_file():
        mb = mp.stat().st_size / 1048576.0
        for m in re.finditer(r"(\d+\.?\d*)MB", text):
            claim = float(m.group(1))
            ck("D", "体积声明 %.1fMB 与实际 %.2fMiB 相符" % (claim, mb),
               abs(claim - mb) <= 0.15, "实际 %.2f MiB" % mb, level="WARN")

    # 正文点名的脚本必须存在（含 tests/ 与 tools/ 里的入口，不止 scripts/）
    have = set()
    for sub in ("scripts", "tests", "test", "tools"):
        d = root / sub
        if d.is_dir():
            have |= {p.name for p in d.glob("*.py")}
    named = set(re.findall(r"([a-z_][a-z0-9_]*\.py)", text))
    miss = sorted(n for n in named if n not in have)
    ck("D", "正文点名的脚本全部存在", not miss, "缺失 %s" % miss)

    # 正文点名的 references 文件必须存在
    refmiss = sorted({n for n in re.findall(r"references/([\w\-]+\.\w+)", text)
                      if not (ref / n).exists()})
    ck("D", "正文点名的 references 全部存在", not refmiss, "缺失 %s" % refmiss)
    # 正文点名的 docs 必须存在
    docmiss = sorted({n for n in re.findall(r"docs/([\w\-]+\.md)", text)
                      if not (root / "docs" / n).exists()})
    ck("D", "正文点名的 docs 全部存在", not docmiss, "缺失 %s" % docmiss)


# ══ E 指针 ══════════════════════════════════════════════════════════
def dim_e(root: Path, text):
    print("\n[E] 子文件指针")
    docs = sorted(p.name for p in (root / "docs").glob("*.md")) if (root / "docs").is_dir() else []
    orphan = [d for d in docs if d not in text and d not in DOC_NO_POINTER]
    ck("E", "功能类 docs 全部在正文有指针", not orphan, "孤儿 %s" % orphan)

    ref = root / "references"
    refs = sorted(p.name for p in ref.iterdir() if p.is_file()) if ref.is_dir() else []
    orph = [r for r in refs if r not in text and r not in REF_NO_POINTER]
    ck("E", "references 全部在正文有指针", not orph, "孤儿 %s" % orph)

    scripts = sorted(p.name for p in (root / "scripts").glob("*.py"))
    # v0.2.274：判据升级为「真实可达性」（同一个 orphan_scan 口径）——
    # 只要能从入口经 import/字符串调用走到、或在 shipped doc 里以
    # `scripts/x.py` 可执行形态点名，就算有人调用；两者皆无才算孤儿。
    try:
        import orphan_scan
        rep = orphan_scan.scan(str(root))
        dead = [r["script"] for r in rep["table"] if r["status"] in ("ORPHAN", "MENTION")]
        ck("E", "每个脚本都有调用方或可执行文档指令", not dead,
           "孤儿 %s" % dead[:8])
        dead_data = [d["file"] for d in rep["data"]
                     if d["status"] in ("ORPHAN", "WEAK", "STALE")]
        ck("E", "每份数据都有读取方（代码或读法指令）", not dead_data,
           "零消费数据 %s" % dead_data[:8])
        ck("E", "文档点名的实体文件全部存在（无悬空引用）",
           not rep["dangling"], "悬空 %s" % [d["ref"] for d in rep["dangling"][:6]])
    except Exception as exc:  # 扫描器自身坏了要看得见，不许静默跳过
        ck("E", "可达性扫描可执行", False, f"orphan_scan 异常：{exc}")


# ══ F 数据契约 ══════════════════════════════════════════════════════
def dim_f(root: Path):
    print("\n[F] 数据契约")
    ref = root / "references"
    bad, nom, total = [], [], 0
    for p in sorted(ref.glob("*.json")):
        total += 1
        try:
            d = json.loads(read(p))
        except Exception as e:
            bad.append("%s: %s" % (p.name, str(e)[:40]))
            continue
        if isinstance(d, dict) and "_meta" not in d:
            nom.append(p.name)
    ck("F", "references JSON 全部可解析", not bad, "; ".join(bad[:3]))
    ck("F", "%d 份 JSON 中有 _meta 溯源块" % total,
       len(nom) <= total // 3, "缺 _meta: %s" % nom[:6], level="WARN")


# ══ G 串台与占位 ════════════════════════════════════════════════════
def dim_g(root: Path, text):
    print("\n[G] 串台 / 占位 / 泄漏")
    hit = [w for w in CROSSTALK if w in text]
    ck("G", "无其他技能的规则串台", not hit, "命中 %s" % hit)
    brk = [w for w in BROKEN_PHRASE if w in text]
    ck("G", "无替换失败残句", not brk, "命中 %s" % brk)
    ph = [w for w in PLACEHOLDER if w in text]
    ck("G", "无占位符残留", not ph, "命中 %s" % ph)

    # 绝对路径 / 用户名泄漏（扫描全部文本文件）
    leaks = []
    NOT_SHIPPED = (".git", "__pycache__", "worldstip-out", "releases", "tests", "test", "fixtures")
    import getpass
    user = getpass.getuser()
    for p in root.rglob("*"):
        if not p.is_file() or any(d in p.parts for d in NOT_SHIPPED):
            continue
        if p.suffix.lower() in (".zip", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".pdf"):
            continue
        try:
            body = read(p)
        except Exception:
            continue
        for pat in (r"[A-Za-z]:\\+Users\\+(?!<)", r"/home/[a-z]+/", re.escape(user)):
            if re.search(pat, body):
                leaks.append("%s (%s)" % (p.relative_to(root), pat))
                break
    ck("G", "包内无绝对路径/用户名", not leaks, "; ".join(leaks[:4]))


# ══ H 测试 ══════════════════════════════════════════════════════════
def dim_h(root: Path):
    print("\n[H] 测试接线")
    run = root / "tests" / "run_all.py"
    ck("H", "统一回归入口存在", run.is_file(), str(run))
    if not run.is_file():
        return
    body = read(run)
    declared = re.search(r"scripts/test_\*\.py\s*(\d+)\s*个", body)
    real = len(list((root / "scripts").glob("test_*.py")))
    ck("H", "回归入口声明的脚本套件数 == 实物",
       (not declared) or int(declared.group(1)) == real,
       "声明 %s / 实物 %d" % (declared.group(1) if declared else "无", real))
    ck("H", "回归入口注册的套件文件都存在",
       all((root / rel).is_file() for rel in re.findall(r'"(tests/[\w_]+\.py)"', body)))


# ══ 包级体检 ════════════════════════════════════════════════════════
# 包内真实入口：统一入口 + 自检/维护 CLI + （若有）测试。其余脚本必须在
# import / subprocess 闭包内，或至少被随包文档写成 `scripts/x.py` 的可执行指令。
ENTRY_SEEDS = ("worldstip.py", "doctor.py", "sync_check.py", "volatile_verify.py")


def transitive_dead(zf, names, doctext):
    """包级传递性死代码：随包但既不在入口闭包里、也没有可执行文档指令的脚本。

    为什么要查传递性：某个脚本本身被 import 着不算数，得看它的 import 方是否
    真能被执行到。实测踩过：compute_plugin / credibility / gate_card 三者在
    裁掉增强渲染器与出境编排的包里没有任何消费者，却因为「文件在包里」而被
    当成能力存在。
    """
    scripts = sorted({n[len("scripts/"):] for n in names
                      if n.startswith("scripts/") and n.endswith(".py")})
    if not scripts:
        return []
    stems = {s[:-3]: s for s in scripts}
    graph = {}
    for s in scripts:
        body = zf.read("scripts/" + s).decode("utf-8", "replace")
        deps = set()
        for m in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", body, re.M):
            if m.group(1) in stems:
                deps.add(stems[m.group(1)])
        for m in re.finditer(r"([A-Za-z_]\w*)\.py\b", body):
            if m.group(1) in stems:
                deps.add(stems[m.group(1)])
        graph[s] = deps
    seeds = {s for s in ENTRY_SEEDS if s in scripts}
    for n in names:
        if n.startswith("tests/") and n.endswith(".py"):
            body = zf.read(n).decode("utf-8", "replace")
            for st, fn in stems.items():
                if re.search(r"\b%s\b" % re.escape(st), body):
                    seeds.add(fn)
    seen, q = set(seeds), list(seeds)
    while q:
        cur = q.pop()
        for nxt in graph.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    dead = []
    for s in scripts:
        if s in seen:
            continue
        if ("scripts/" + s) in doctext or s in doctext:
            continue   # 文档给了可执行形态，算「有调用方」（模型会真跑）
        dead.append(s)
    return dead


def pack_check(zip_path: Path, src_root: Path):
    print("\n[X] 包级（解压后实检）")
    zf = zipfile.ZipFile(str(zip_path))
    names = zf.namelist()
    ck("X", "包根有 SKILL.md", "SKILL.md" in names, "文件数 %d" % len(names))
    ck("X", "无外层包裹目录",
       not (any("/" in n for n in names) and "SKILL.md" not in names))
    deep = max([n.count("/") for n in names] or [0])
    ck("X", "包内目录层数 <= 2", deep <= 2, "最深 %d" % deep)
    ck("X", "无缓存夹带", not [n for n in names if "__pycache__" in n or n.endswith(".pyc")])

    text = zf.read("SKILL.md").decode("utf-8")
    # 悬空指针：正文指向的文件必须真在包里
    ghost = []
    for pre in ("docs/", "references/", "scripts/"):
        for n in re.findall(re.escape(pre) + r"([\w\-]+\.\w+)", text):
            if pre + n not in names:
                ghost.append(pre + n)
    ck("X", "正文引用的文件全部在包内", not ghost, "悬空 %s" % sorted(set(ghost))[:6])

    # 跨平台漂移：description 触发面与版本号
    fm = frontmatter(text)
    desc = fm.get("description", "")
    cand = [w.strip() for w in re.split(r"[、，,；;]", desc) if 2 <= len(w.strip()) <= 8]
    ck("X", "包内 description 保留触发短语 >= %d" % TRIGGER_MIN,
       len(cand) >= TRIGGER_MIN, "实得 %d 个" % len(cand))
    ver = json.loads(read(src_root / "VERSION.json")).get("version")
    for field in ("description_zh", "description_en", "summary"):
        val = fm.get(field) or ""
        stale = {v for v in re.findall(r"v?(\d+\.\d+\.\d+)", val) if v != ver}
        ck("X", "包内 %s 无旧版本残留" % field, not stale, "发现 %s" % sorted(stale))

    # 脚本依赖的 references：要么在包内，要么 SKILL.md 已声明「本包裁剪了它」。
    # 只认「声明 + 脚本自带降级」这一种缺口 —— 真的漏拷文件还是会被抓出来。
    DECLARED = ("未随本包分发", "未随包提供", "需另行安装", "本次未提供")
    declared = any(w in text for w in DECLARED)
    missing = []
    for n in names:
        if not n.startswith("scripts/") or not n.endswith(".py"):
            continue
        body = zf.read(n).decode("utf-8", "replace")
        for dep in set(re.findall(r'references/([\w\-]+\.json)', body)):
            if "references/" + dep not in names:
                if declared:
                    continue
                missing.append("%s -> %s" % (n, dep))
    ck("X", "脚本依赖的 references 齐全或已声明裁剪", not missing,
       "缺失 %s（SKILL.md 未声明裁剪）" % missing[:6])

    ck("X", "包内无 http(s) 外链（千问档要求）",
       not re.search(r"https?://", text), "命中 %s" % re.findall(r"https?://\S{0,20}", text)[:3],
       level="WARN")

    # 传递性死代码 + 载荷一致性
    doctext = text
    for n in names:
        if n.endswith(".md") and n != "SKILL.md":
            doctext += "\n" + zf.read(n).decode("utf-8", "replace")
    dead = transitive_dead(zf, names, doctext)
    ck("X", "包内脚本都在入口闭包内或有可执行文档指令", not dead,
       "随包但无人调用 %s" % dead[:6])


def main(argv=None):
    ap = argparse.ArgumentParser(description="八维度技能自检")
    ap.add_argument("--root", default=str(ROOT), help="技能源码根目录")
    ap.add_argument("--pack", action="append", default=None,
                    help="额外体检已构建的 zip（可多次）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    print("SELFCHECK root=%s" % root)
    text = dim_a(root)
    if text is None:
        return 1
    fm = frontmatter(text)
    dim_b(fm)
    dim_c(root, fm, text)
    dim_d(root, text)
    dim_e(root, text)
    dim_f(root)
    dim_g(root, text)
    dim_h(root)
    for z in (args.pack or []):
        pack_check(Path(z), root)

    # 四个包齐了才谈得上「跨平台差异」：差异表必须与实测包一致，
    # 否则文档说「这个包缺什么」也会漂。
    if len(args.pack or []) >= 4:
        print("\n[X] 跨平台差异台账（docs/PLATFORMS.md）")
        rc = 1
        try:
            import platform_diff as PD
            rc = PD.main(["--check"])
        except SystemExit as e:
            rc = int(e.code or 0)
        except Exception as e:      # 工具本身炸了也要记成失败，不能静默放行
            print("  平台差异检查异常: %s: %s" % (type(e).__name__, e))
        ck("X", "跨平台差异表与实测包一致", rc == 0,
           "platform_diff --check 返回 %s（跑 --write 更新）" % rc)

    fails = [r for r in RESULTS if not r["ok"] and r["detail"] != ""]
    hard = [r for r in RESULTS if not r["ok"] and not r["name"].endswith("WARN")]
    warns = [r for r in RESULTS if not r["ok"] and r["name"].endswith("WARN")]
    # 重新按 level 归类（WARN 项不阻断）
    hard = [r for r in RESULTS if not r["ok"] and r["dim"] and r["name"] and
            not any(w in r["name"] for w in ("长度", "体积声明", "有指针或有调用方", "_meta 溯源"))]
    warns = [r for r in RESULTS if not r["ok"] and r not in hard]

    print("\n" + "-" * 68)
    print("合计 %d 项：通过 %d / 失败 %d / 提示 %d"
          % (len(RESULTS), len(RESULTS) - len(hard) - len(warns), len(hard), len(warns)))
    for r in hard:
        print("  FAIL [%s] %s  %s" % (r["dim"], r["name"], r["detail"]))
    print("SELFCHECK: %s" % ("PASS" if not hard else "FAIL"))
    if args.json:
        print(json.dumps({"items": RESULTS, "fail": len(hard), "warn": len(warns)},
                         ensure_ascii=False, indent=1))
    return 0 if not hard else 1


if __name__ == "__main__":
    sys.exit(main())
