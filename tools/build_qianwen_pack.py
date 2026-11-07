#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_qianwen_pack.py — 千问 AI 平台（platform.qianwenai.com）发布包。

官方硬约束：
  1. ZIP 根目录必须有 `SKILL.md`（不能被外层目录包裹）
  2. 整包体积 <= 10 MiB（校验的是 zip，不是解压后）
  3. frontmatter 的 `---` 内必须有 `name` 与 `description`

平台另有「安全绿网」内容扫描。按实际驳回记录与被驳回包的全量扫描，
本包的净化口径如下（与 WorkBuddy 包共用裁剪集，再叠加三层）：

  A. 剔除开发过程文档（对终端用户零价值，且逐字列举了敏感地名/机构词）
     CHANGELOG.md / DoD.md / QC_REPORT.md / INSTALL.md / ANTI_DISTILL.md /
     报告生成规范.md / 排版规范.md
  B. 数据来源标注里的真实域名 -> 机构名（保留可核验性，去掉外链 token）
     cs.mfa.gov.cn -> 中国领事服务网；gov.cn -> 中国政府网；其余 .gov 类
     归一到「该国官方 xx 部门网站」；最后兜底为「官方渠道」
  C. SKILL.md 末行的许可声明去掉单方限制性条款，只留署名 + MIT 许可

**保留不动**（已逐条核对，改了会破坏事实准确性或功能）：
  - 脚本里的「台湾 / 香港 / 澳门」：是用户输入匹配别名与坐标字典键
    （同时包含「中国台湾 / 中国香港 / 中国澳门」规范写法），属逻辑标识符
  - 「南海区 / 南海神庙 / 钓鱼岛（吉林景点）/ 川藏南线」：同名词，非主权表述
  - 「全国最早」「100% 有链接」「客运班车最便宜」：客观事实与功能对比

用法：
    python tools/build_qianwen_pack.py [--out PATH]
"""
import argparse
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_pack as BP              # noqa: E402
import build_workbuddy_pack as BWB   # noqa: E402

LIMIT = 10 * 1024 * 1024

# A. 开发过程文档
EX_QW_DOCS = {
    "CHANGELOG.md", "DoD.md", "QC_REPORT.md", "INSTALL.md",
    "ANTI_DISTILL.md", "报告生成规范.md", "排版规范.md",
}

# B. 域名 -> 机构名（先去重复，再换裸域名，最后兜底）
DEDUP = (
    (r"中国领事服务网\s*cs\.mfa\.gov\.cn\s*", "中国领事服务网 "),
    (r"中国领事服务网\s*mfa\.gov\.cn\s*", "中国领事服务网 "),
    (r"中国政府网\s*gov\.cn\s*", "中国政府网 "),
    (r"\s*[（(]?\s*App\s*/\s*官网\s*www\.12306\.cn\s*[）)]?", "（App / 官网）"),
    (r"travel\.state\.gov", "该国官方外交部门网站"),
)
# PRECISE 对所有文本生效（含 .py：gate_card.py 里有 cs.mfa.gov.cn 文案）
PRECISE = (
    (re.compile(r"cs\.mfa\.gov\.cn"), "中国领事服务网"),
    (re.compile(r"(?<![a-z0-9.\-])mfa\.gov\.cn"), "中国领事服务网"),
    (re.compile(r"(?<![a-z0-9.\-])fmprc\.gov\.cn"), "中国外交部官网"),
    (re.compile(r"(?:[a-z0-9\-]+\.)*china-embassy\.gov\.[a-z]{2}"),
     "中国驻当地使领馆官网"),
    (re.compile(r"(?:[a-z0-9\-]+\.)*state\.gov"), "该国官方外交部门网站"),
    (re.compile(r"(?:[a-z0-9\-]+\.)*immigration\.gov\.[a-z]{2}"), "该国官方移民部门网站"),
    (re.compile(r"(?:[a-z0-9\-]+\.)*(?:etravel|arrival)\.gov\.[a-z]{2}"),
     "该国官方入境登记网站"),
    (re.compile(r"(?<![a-z0-9.\-])gov\.cn"), "中国政府网"),
)
# FALLBACK 只对 .md/.json 生效，且末尾加 (?![a-z0-9])：
# 否则会命中代码里的 re.compile（"re.com"+ "pile"）之类，把源码改成中文标识符。
FALLBACK = (
    (re.compile(r"(?:[a-z0-9\-]+\.)+(?:gov|com|cn|net|org|io)(?:\.[a-z]{2})?(?![a-z0-9])"),
     "官方渠道"),
)
TEXT_EXT = (".md", ".json", ".py", ".txt")
DOC_EXT = (".md", ".json", ".txt")

# C. SKILL.md 专属改写
QW_SKILL_SUBS = (
    ("，变更要点见 `CHANGELOG.md`。", "。"),
    ("*© WorldsTip by MrdT · 本技能以 MIT 许可发布并附加反蒸馏条款："
     "禁止未授权搬运、二次分发或用于模型训练/蒸馏；核心 POI 与气候数据受保护，"
     "详见包内 `ANTI_DISTILL.md`。*",
     "*© WorldsTip by MrdT · 本技能以 MIT 许可发布；核心 POI 与气候数据受保护。*"),
)

TEXT_EXT = (".md", ".json", ".py", ".txt")

DOMAIN = re.compile(r"[a-z0-9.\-]*(?:worldstip\.com|qianwenai\.com|github\.com|"
                    r"openstreetmap\.org|unpkg\.com|w3\.org)", re.I)
URL = re.compile(r"https?://")
SENSITIVE = ("政治",)
# 替换误伤信号：中文替换词紧贴 ASCII 字母/点（说明命中的是标识符片段，如 re.com*pile*）
DAMAGE = re.compile(r"[A-Za-z]官方渠道|官方渠道[A-Za-z]")


def scrub_origins(text, fallback_ok=False):
    for pat, rep in DEDUP:
        text = re.sub(pat, rep, text)
    for pat, rep in PRECISE:
        text = pat.sub(rep, text)
    if fallback_ok:
        for pat, rep in FALLBACK:
            text = pat.sub(rep, text)
    return text


def build(out):
    items = []
    for rel, p in BP.collect():
        top = rel.split("/")[0]
        if "/" in rel and top in BWB.EX_DIRS:
            continue
        if rel in BWB.EX_FILES or rel in EX_QW_DOCS:
            continue
        items.append((rel, p))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in items:
            data = BP.pack_bytes(p)
            if rel.lower().endswith(TEXT_EXT):
                text = data.decode("utf-8")
                if rel == "SKILL.md":
                    text = BWB.patch_skill(text, align_display=False)
                    for a, b in QW_SKILL_SUBS:
                        text = text.replace(a, b)
                elif rel == "README.md":
                    text = BWB.patch_readme(text)
                text = scrub_origins(text, fallback_ok=rel.lower().endswith(DOC_EXT))
                data = text.encode("utf-8")
            zi = zipfile.ZipInfo(rel, date_time=(2026, 11, 7, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zi.create_system = 3
            z.writestr(zi, data)
    return out


def report(out):
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        domains = urls = sensitive = 0
        hits = []
        for n in names:
            if not n.lower().endswith(TEXT_EXT + (".svg",)):
                continue
            t = z.read(n).decode("utf-8", errors="replace")
            d = DOMAIN.findall(t)
            u = URL.findall(t)
            s = sum(t.count(w) for w in SENSITIVE)
            domains += len(d)
            urls += len(u)
            sensitive += s
            if d or u or s:
                hits.append((n, len(d), len(u), s))
        skill = z.read("SKILL.md").decode("utf-8")

    size = os.path.getsize(out)
    parts = skill.split("---")
    fm = parts[1] if skill.startswith("---") and len(parts) >= 3 else ""
    # 替换误伤自检：任何 .py 出现中文替换词紧贴字母，说明把源码标识符改坏了
    damage = []
    with zipfile.ZipFile(out) as z:
        for n in names:
            if not n.endswith(".py"):
                continue
            t = z.read(n).decode("utf-8", errors="replace")
            for m in DAMAGE.finditer(t):
                damage.append("%s: %s" % (n, t[max(0, m.start() - 20):m.end() + 15]))
    checks = [
        ("ZIP <= 10MiB", size <= LIMIT, "%d bytes (%.2f MiB)" % (size, size / 1048576.0)),
        ("根目录 SKILL.md", "SKILL.md" in names, "文件数 %d" % len(names)),
        ("无外层目录", not (any("/" in n for n in names) and "SKILL.md" not in names), ""),
        ("frontmatter name", bool(re.search(r"^name:\s*\S+", fm, re.M)), ""),
        ("frontmatter description", bool(re.search(r"^description:\s*\S+", fm, re.M)), ""),
        ("零外链域名", domains == 0, "命中 %d" % domains),
        ("零 http(s) URL", urls == 0, "命中 %d" % urls),
        ("零高敏词", sensitive == 0, "命中 %s" % (SENSITIVE,)),
        ("无开发文档夹带", not (set(names) & EX_QW_DOCS), str(sorted(set(names) & EX_QW_DOCS))),
        ("替换无源码误伤", not damage, str(damage[:3])),
    ]
    print("包路径 : %s" % out)
    for name, ok, detail in checks:
        print("  %s  %-26s %s" % ("PASS" if ok else "FAIL", name, detail))
    if hits:
        print("命中明细: %s" % hits[:6])
    ok = all(c[1] for c in checks)
    print("RESULT: %s" % ("PASS" if ok else "FAIL"))
    return ok


def main():
    ap = argparse.ArgumentParser(description="构建千问 AI 平台发布包")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or os.path.join(
        os.path.dirname(BP.ROOT), "dist",
        "worldstip-travel-planner-v%s-qianwen.zip" % BP.VER)
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    build(out)
    return 0 if report(out) else 1


if __name__ == "__main__":
    sys.exit(main())
