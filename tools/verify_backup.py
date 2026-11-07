#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_backup.py — GitHub 备份完整性确定性自检（零联网、零写入）。

用途：clone 到任意机器后，一条命令确认「源码 + 专家包 + 四平台上传包」
是否完整、版本是否对齐、隔离资产是否误入上传包。

    python tools/verify_backup.py            # 任一失败 EXIT 1
    python tools/verify_backup.py --json     # 机器可读结果

判据全部是确定性纯函数：不依赖运行时推断，不输出「看起来没问题」。
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.dirname(ROOT) + "/dist"
RELEASES = ROOT + "/releases"

WB_LIMIT = 3 * 1024 * 1024          # WorkBuddy：解压后上限 3145728 字节
QW_LIMIT = 10 * 1024 * 1024         # 千问：zip 文件上限 10 MiB
PLATFORMS = ("workbuddy", "skillhub", "dumate", "qianwen")
ISOLATED = ("HANDOFF.md", "expert/", "build_expert_pack.py", "verify_backup.py")

results = []


def check(name, ok, detail="", skip=False):
    """skip=True 表示该项在当前环境不适用（如实标 SKIP，不伪装成 PASS 绿灯）。"""
    results.append({"item": name, "ok": bool(ok), "detail": str(detail),
                    "skip": bool(skip)})


def read(p):
    with open(p, "rb") as f:
        return f.read()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def version_truth():
    d = json.loads(read(ROOT + "/VERSION.json").decode("utf-8"))
    return d["version"]


def frontmatter_version(data):
    m = re.search(rb"(?m)^version:\s*([0-9][0-9A-Za-z.\-]*)\s*$", data[:4000])
    return m.group(1).decode("ascii") if m else ""


def main_checks():
    # 1. 版本真源
    try:
        ver = version_truth()
        check("VERSION.json 可解析", bool(re.match(r"^\d+\.\d+\.\d+[0-9A-Za-z.\-]*$", ver)), ver)
    except Exception as e:
        check("VERSION.json 可解析", False, str(e))
        return

    skill_path = ROOT + "/SKILL.md"
    skill = read(skill_path)
    check("SKILL.md 恰为 500 行", len(skill.splitlines()) == 500,
          "%d 行" % len(skill.splitlines()))
    check("SKILL.md 纯 LF", b"\r" not in skill, "含 CR" if b"\r" in skill else "LF")
    check("SKILL.md 版本与真源一致", frontmatter_version(skill) == ver,
          "SKILL.md=%s / VERSION.json=%s" % (frontmatter_version(skill), ver))
    check("SKILL.md 位于仓库根", os.path.isfile(skill_path), skill_path)

    # 2. 关键源码目录
    for d in ("scripts", "references", "docs", "tools", "tests", "fixtures", "assets",
              "expert/worldstip-travel-expert"):
        check("源码目录存在 %s/" % d, os.path.isdir(ROOT + "/" + d), d)

    # 3. 专家包源码
    edir = ROOT + "/expert/worldstip-travel-expert"
    for f in ("README.md", "LICENSE", "ANTI_DISTILL.md",
              ".codebuddy-plugin/plugin.json", "agents/worldstip-travel-expert.md",
              "avatars/expert.png",
              "skills/worldstip-travel-planner/SKILL.md",
              "skills/worldstip-travel-planner/references/README.md"):
        check("专家源码含 %s" % f, os.path.isfile(edir + "/" + f), f)
    try:
        pj = json.loads(read(edir + "/.codebuddy-plugin/plugin.json").decode("utf-8"))
        check("plugin.json 可解析且 name 正确",
              pj.get("name") == "worldstip-travel-expert", str(pj.get("name")))
        check("plugin.json 版本独立成线", bool(pj.get("version")),
              "专家包 %s / 技能 %s" % (pj.get("version"), ver))
        check("plugin.json author 含 email",
              bool(pj.get("author", {}).get("email")), str(pj.get("author")))
        for rel in list(pj.get("agents", [])) + [pj.get("avatar", "")]:
            rel = rel.lstrip("./")
            check("plugin.json 指向真实文件 %s" % rel, os.path.isfile(edir + "/" + rel), rel)
    except Exception as e:
        check("plugin.json 可解析且 name 正确", False, str(e))
    try:
        png = read(edir + "/avatars/expert.png")
        w, h = struct.unpack(">II", png[16:24])
        check("头像 PNG 512×512", png[:8] == b"\x89PNG\r\n\x1a\n" and (w, h) == (512, 512),
              "%dx%d, %d bytes" % (w, h, len(png)))
    except Exception as e:
        check("头像 PNG 512×512", False, str(e))

    # 3b. WorkBuddy 官方专家包结构（2026-11-07 design-experts 样板对照）
    skill_dir = edir + "/skills/worldstip-travel-planner"
    try:
        inner = read(skill_dir + "/SKILL.md").decode("utf-8")
        im = re.match(r"^---\n(.*?)\n---", inner, re.S)
        ikeys = set(re.findall(r"^([A-Za-z_][A-Za-z0-9_-]*):",
                               im.group(1), re.M)) if im else set()
        check("内嵌技能 frontmatter 为 title/summary/read_when",
              {"title", "summary", "read_when"} <= ikeys, str(sorted(ikeys)))
        overlap = {"name", "version", "description", "allowed-tools"} & ikeys
        check("内嵌技能不混入独立包字段", not overlap, str(sorted(overlap)))
        check("内嵌技能声明单一真源版本", ver in inner, ver)
        check("内嵌技能不复制 500 行正文",
              "不是技能正文副本" in inner and "不复制" in inner, "")
    except Exception as e:
        check("内嵌技能 frontmatter 为 title/summary/read_when", False, str(e))
    try:
        ag = read(edir + "/agents/worldstip-travel-expert.md").decode("utf-8")
        am = re.match(r"^---\n(.*?)\n---", ag, re.S)
        akeys = set(re.findall(r"^([A-Za-z_][A-Za-z0-9_-]*):",
                               am.group(1), re.M)) if am else set()
        check("Agent frontmatter 含 tools 与 skills",
              {"tools", "skills"} <= akeys, str(sorted(akeys)))
        bound = re.search(r"^skills:\s*\[([^\]]+)\]", am.group(1), re.M)
        bound_names = [x.strip() for x in bound.group(1).split(",")] if bound else []
        check("Agent 绑定的内嵌技能真实存在",
              bool(bound_names) and all(os.path.isdir(edir + "/skills/" + n)
                                       for n in bound_names), str(bound_names))
        dup = {"displayName", "profession"} & akeys
        check("Agent 不重复声明 plugin.json 已有的展示字段", not dup, str(sorted(dup)))
    except Exception as e:
        check("Agent frontmatter 含 tools 与 skills", False, str(e))

    # 4. 四个平台上传包
    # 权威副本是 releases/（GitHub 里唯一被跟踪的 zip）；dist/ 是本地构建产物，
    # clone 出来的机器通常没有它 —— 缺 dist 不算失败，如实标 SKIP。
    for pf in PLATFORMS:
        base = "worldstip-travel-planner-v%s-%s.zip" % (ver, pf)
        dp, rp = DIST + "/" + base, RELEASES + "/" + base
        if not os.path.isfile(rp):
            check("releases 含 %s" % base, False, "文件不存在")
            continue
        check("releases 含 %s" % base, True, "%d bytes" % os.path.getsize(rp))
        try:
            z = zipfile.ZipFile(rp)
            names = z.namelist()
            bad = z.testzip()
            check("%s zip 结构无损" % pf, bad is None, str(bad))
            check("%s 根级 SKILL.md" % pf, "SKILL.md" in names, "")
            check("%s 包内版本对齐" % pf, frontmatter_version(z.read("SKILL.md")) == ver,
                  frontmatter_version(z.read("SKILL.md")))
            leaks = sorted({k for k in ISOLATED
                            if any(k in n for n in names)})
            check("%s 未夹带接手资产" % pf, not leaks, ",".join(leaks))
            if pf == "workbuddy":
                un = sum(i.file_size for i in z.infolist())
                check("WorkBuddy 解压 <= 3 MiB", un <= WB_LIMIT,
                      "%d / %d bytes" % (un, WB_LIMIT))
                check("WorkBuddy 含真实 LICENSE", "LICENSE" in names, "")
            if pf == "qianwen":
                check("千问 zip <= 10 MiB", os.path.getsize(rp) <= QW_LIMIT,
                      "%d bytes" % os.path.getsize(rp))
            if pf == "skillhub":
                check("SkillHub 含 _meta.json", "_meta.json" in names, "")
                if "_meta.json" in names:
                    meta = json.loads(z.read("_meta.json").decode("utf-8"))
                    check("SkillHub 内部版本对齐", meta.get("internalVersion") == ver,
                          str(meta.get("internalVersion")))
            if pf == "dumate":
                check("DuMate 含 PLATFORM.md", "PLATFORM.md" in names, "")
        except Exception as e:
            check("%s zip 结构无损" % pf, False, str(e))

        if os.path.isfile(dp):
            check("dist/%s 与 releases 字节一致" % pf,
                  sha(read(rp)) == sha(read(dp)), "")
        else:
            check("dist/%s 与 releases 字节一致" % pf, True,
                  "本地 dist/ 不存在，备份以 releases/ 为准", skip=True)

    # 5. 专家 zip 与辅助技能包
    ez = "worldstip-travel-expert.zip"
    rel_ez = RELEASES + "/" + ez
    if os.path.isfile(rel_ez):
        z = zipfile.ZipFile(rel_ez)
        names = z.namelist()
        check("专家 zip 结构无损", z.testzip() is None, str(z.testzip()))
        check("专家 zip 保留外层目录",
              all(n.startswith("worldstip-travel-expert/") for n in names),
              "%d 项" % len(names))
        check("专家 zip 含 plugin.json",
              "worldstip-travel-expert/.codebuddy-plugin/plugin.json" in names, "")
        for rel in ("worldstip-travel-expert/skills/worldstip-travel-planner/SKILL.md",
                    "worldstip-travel-expert/skills/worldstip-travel-planner/references/README.md"):
            check("专家 zip 含内嵌技能文件 %s" % rel.split("/")[-1], rel in names, rel)
        if os.path.isfile(DIST + "/" + ez):
            check("dist 专家 zip 与 releases 字节一致",
                  sha(read(rel_ez)) == sha(read(DIST + "/" + ez)), "")
        else:
            check("dist 专家 zip 与 releases 字节一致", True,
                  "本地 dist/ 不存在，备份以 releases/ 为准", skip=True)
    else:
        check("releases 含专家 zip", False, "文件不存在")

    helper = "delivery-no-pseudoblock-v0.2.22-workbuddy.zip"
    check("releases 含辅助技能包 %s" % helper, os.path.isfile(RELEASES + "/" + helper), "")

    # 6. 接手文档
    hd = ROOT + "/HANDOFF.md"
    if os.path.isfile(hd):
        t = read(hd).decode("utf-8")
        for key in ("SKILL.md", "build_release_packs.py", "build_qianwen_pack.py",
                    "verify_backup.py", ver):
            check("HANDOFF.md 含关键项 %s" % key, key in t, "")
    else:
        check("HANDOFF.md 存在", False, "文件不存在")


def main():
    ap = argparse.ArgumentParser(description="GitHub 备份完整性自检")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    main_checks()
    failed = [r for r in results if not r["ok"]]
    skipped = [r for r in results if r.get("skip")]
    if a.json:
        print(json.dumps({"pass": not failed, "total": len(results),
                          "failed": len(failed), "skipped": len(skipped),
                          "items": results}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            tag = "FAIL" if not r["ok"] else ("SKIP" if r.get("skip") else "PASS")
            print("  %s  %-46s %s" % (tag, r["item"], r["detail"]))
        print("-" * 72)
        print("BACKUP: %s  |  %d 项检查，%d 项失败，%d 项不适用(SKIP)" %
              ("PASS" if not failed else "FAIL", len(results),
               len(failed), len(skipped)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
