#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_expert_pack.py — 从 expert/ 源码确定性重建 WorkBuddy 专家包 zip。

与技能包构建器保持同一套纪律：
  - 包内保留外层目录 worldstip-travel-expert/（专家包约定，与技能包相反）
  - 固定时间戳、稳定排序、文本统一 LF，同输入产出字节可复现
  - --verify 逐条目比对 zip 内字节与源码，不一致即 EXIT 1
  - 只收集常规资产，排除缓存与隐藏文件

用法：
    python tools/build_expert_pack.py --verify
    python tools/build_expert_pack.py --out releases/worldstip-travel-expert.zip --verify
"""
from __future__ import print_function

import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "expert", "worldstip-travel-expert")
OUTER = "worldstip-travel-expert"
STAMP = (2026, 11, 7, 0, 0, 0)
TEXT_EXT = {".md", ".json", ".txt", ".yml", ".yaml"}
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}
SKIP_NAMES = {".gitkeep", ".DS_Store"}


def pack_bytes(path):
    data = open(path, "rb").read()
    if os.path.splitext(path)[1].lower() in TEXT_EXT or os.path.basename(path) in {"LICENSE", "NOTICE"}:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return data


def collect():
    """返回 [(zip 内相对路径, 本地绝对路径)]，按 zip 内路径稳定排序。"""
    items = []
    for dp, dn, fn in os.walk(SRC):
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS)
        for f in sorted(fn):
            if f in SKIP_NAMES or f.startswith("."):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, SRC).replace("\\", "/")
            items.append((OUTER + "/" + rel, p))
    return sorted(items)


def check_versions():
    """专家包版本三处一致 + 内嵌技能版本跟得上源码。

    三处：plugin.json 的 version / README 的「专家包版本」行 / agents 标题行的（vX.Y.Z）。
    另加一处：内嵌技能入口声明的技能版本必须 == VERSION.json 的 version
    （内嵌技能版本不随专家包升，但必须与所嵌技能的当前版本一致）。
    """
    import json
    import re
    plugin = os.path.join(SRC, ".codebuddy-plugin", "plugin.json")
    readme = os.path.join(SRC, "README.md")
    agent = os.path.join(SRC, "agents", "worldstip-travel-expert.md")
    skill = os.path.join(SRC, "skills", "worldstip-travel-planner", "SKILL.md")
    ver = json.load(open(plugin, encoding="utf-8")).get("version", "")
    rd = open(readme, encoding="utf-8").read()
    ag = open(agent, encoding="utf-8").read()
    sk = open(skill, encoding="utf-8").read()
    m_readme = re.search(r"专家包版本 \| `([0-9.]+)`", rd)
    m_agent = re.search(r"^#\s+.*?（v([0-9.]+)）", ag, re.M)
    skill_ver = json.load(open(os.path.join(ROOT, "VERSION.json"), encoding="utf-8"))["version"]
    rows = [
        ("plugin.json version", ver or "缺失", bool(ver)),
        ("README 版本行", m_readme.group(1) if m_readme else "缺失", bool(m_readme)),
        ("agents 标题行（vX）", m_agent.group(1) if m_agent else "缺失", bool(m_agent)),
    ]
    ok = True
    for label, got, present in rows:
        good = present and got == ver
        ok = ok and good
        print("  %s %-22s %s%s" % ("PASS" if good else "FAIL", label, got,
                                   "" if good else "  ≠ %s" % ver))
    # 内嵌技能版本：文档里出现任何非当前技能版本号，即判漂移。
    # 原正则写死 0\.2\.(\d+)：技能一旦升到 0.3.x 就再也匹配不到，wrong 恒为空，
    # 这条判据会静默变成永远 PASS。改为抓任意 x.y.z 三段号再与真源比对。
    # README 天然含专家包自身版本（如 1.0.0），那是另一条版本线，不是技能漂移，须排除。
    found = set(re.findall(r"\b\d+\.\d+\.\d+\b", sk + rd))
    wrong = sorted(v for v in found if v != skill_ver and v != ver)
    good = not wrong
    ok = ok and good
    print("  %s %-22s %s%s" % ("PASS" if good else "FAIL", "内嵌技能版本", skill_ver,
                               "" if good else "  残留旧版 %s" % wrong))
    return 0 if ok else 1


def check_compliance(plugin_path=None):
    """平台解析硬约束（不满足即「解析失败」，与 JSON 是否合法无关）。

    这些是平台侧正则/字数限制，构建器必须自己把关——等上传后被拒太晚。
    v0.2.274 起固化为机检：displayName.zh ≤15 字且无空格无括号、
    displayDescription.zh ≤100 字、defaultInitPrompt 与 quickPrompts[0] 逐字一致、
    tags 恰好 3 个、根标志 .codebuddy-plugin/plugin.json 存在。

    plugin_path 可注入：不给则校验本仓库的 plugin.json；给了则用于反向
    自证测试（喂一份故意违规的副本，证明这些判据真的会报错，不是永远 PASS）。
    """
    import json
    import re
    plugin = plugin_path or os.path.join(SRC, ".codebuddy-plugin", "plugin.json")
    rows = []

    # 根标志必须最先单独判。原实现把它放在 rows 末尾，可上面的 json.load 早已执行，
    # 文件不存在会先抛 FileNotFoundError，那条判据永远 PASS、永远不可能 FAIL。
    exists = os.path.isfile(plugin)
    rows.append(("根标志 plugin.json 存在", exists, plugin))
    if not exists:
        for label, good, detail in rows:
            print("  %s %-34s %s" % ("PASS" if good else "FAIL", label,
                                     "" if good else detail))
        return 1

    d = json.load(open(plugin, encoding="utf-8"))

    zh = (d.get("displayName") or {}).get("zh", "")
    rows.append(("displayName.zh ≤15 字", len(zh) <= 15, "%d 字" % len(zh)))
    rows.append(("displayName.zh 无空格", " " not in zh and "\u3000" not in zh, zh))
    rows.append(("displayName.zh 无括号",
                 not any(c in zh for c in "（）()【】[]<>《》"), zh))

    dd = (d.get("displayDescription") or {}).get("zh", "")
    rows.append(("displayDescription.zh ≤100 字", len(dd) <= 100, "%d 字" % len(dd)))

    init = d.get("defaultInitPrompt") or {}
    first = (d.get("quickPrompts") or [{}])[0]
    for k in init:
        rows.append(("defaultInitPrompt.%s == quickPrompts[0]" % k,
                     init[k] == first.get(k), "逐字一致"))
    rows.append(("quickPrompts ≥1", bool(d.get("quickPrompts")), ""))

    rows.append(("tags 恰好 3 个", len(d.get("tags") or []) == 3,
                 "%d 个" % len(d.get("tags") or [])))

    # 声明的相对路径必须在专家包源码里真实存在——「字段填了但文件不在」是
    # 解析层不报、安装后才炸的典型缺陷。基准固定取 SRC 而非 plugin 所在目录：
    # L16 反向自证会把 plugin.json 复制到临时目录，若以副本目录为基准，
    # 所有资产都会被误判缺失，「原样不动」那条也会挂。
    def _has(rel):
        return isinstance(rel, str) and os.path.isfile(os.path.join(SRC, rel))

    av = d.get("avatar") or ""
    rows.append(("avatar 声明文件在包内", bool(av) and _has(av), av or "(缺失)"))

    ags = [a for a in (d.get("agents") or []) if isinstance(a, str)]
    rows.append(("agents 声明文件在包内",
                 bool(ags) and all(_has(a) for a in ags), str(ags or "(缺失)")))

    # agents 的 frontmatter 用 skills: [name] 绑定内嵌技能，入口文件不能缺
    names = []
    for a in ags:
        ap = os.path.normpath(os.path.join(SRC, a))
        if os.path.isfile(ap):
            m = re.search(r"^skills:\s*\[([^\]]*)\]",
                          open(ap, encoding="utf-8").read(), re.M)
            if m:
                names += [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    rows.append(("内嵌技能入口在包内",
                 bool(names) and all(os.path.isfile(
                     os.path.join(SRC, "skills", n, "SKILL.md")) for n in names),
                 str(names or "(缺失)")))

    ok = True
    for label, good, detail in rows:
        ok = ok and good
        print("  %s %-34s %s" % ("PASS" if good else "FAIL", label,
                                 "" if good else detail))
    return 0 if ok else 1


def build(out, verify):
    items = collect()
    if not items:
        print("FAIL 专家源码目录为空：%s" % SRC)
        return 1
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in items:
            zi = zipfile.ZipInfo(rel, date_time=STAMP)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zi.create_system = 3
            z.writestr(zi, pack_bytes(p))
    print("专家包 : %s" % out)
    print("文件数 : %d" % len(items))
    print("体积   : %d bytes" % os.path.getsize(out))

    if verify:
        with zipfile.ZipFile(out) as z:
            bad = [rel for rel, p in items if z.read(rel) != pack_bytes(p)]
            print("字节一致校验: %s" % ("PASS" if not bad else "FAIL " + str(bad[:5])))
            if bad:
                return 1
        print("\n=== 专家包版本一致性 ===")
        if check_versions():
            print("VERSION-CHECK: FAIL")
            return 1
        print("VERSION-CHECK: PASS")
        print("\n=== 平台解析硬约束 ===")
        if check_compliance():
            print("COMPLIANCE: FAIL")
            return 1
        print("COMPLIANCE: PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(description="重建 WorldsTip 旅行规划师专家包")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(ROOT), "dist",
                                                  "worldstip-travel-expert.zip"))
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    return build(a.out, a.verify)


if __name__ == "__main__":
    sys.exit(main())
