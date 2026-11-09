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
  D. 无扩展名文件改名 LICENSE -> LICENSE.md，并同步改写 README 目录树
     平台按**扩展名**判文件类型，无扩展名一律拒收（SkillHub 实测报错
     「不允许的文件类型: LICENSE」）。这条必须进自检 —— 本地门禁只保证
     文件进得去包，管不了平台收不收，全绿也可能被拒。

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
import audit_upload_zip as AU        # noqa: E402  审核器视角硬闸门

LIMIT = 10 * 1024 * 1024

# A. 开发过程文档
EX_QW_DOCS = {
    "CHANGELOG.md", "DoD.md", "QC_REPORT.md", "INSTALL.md",
    "ANTI_DISTILL.md", "报告生成规范.md", "排版规范.md",
}
# 千问包不再整目录排除 docs。原做法把 docs/ 全砍，但 SKILL.md 正文一直指着
# docs/RENDER_SPEC.md 等 9 篇 —— 包内没有就是悬空引用，模型会照着去读一个不存在的文件
# （doctor 的「文档反引号引用无幽灵」当场判 FAIL）。改为白名单：功能文档随包，
# 只排「含 http 外链」与「纯维护/历史」两类。
EX_QW_DIRS = set(BWB.EX_DIRS)
QW_DOCS_KEEP = {
    "GEO_DISAMBIGUATION.md", "GUIDE_SEARCH.md", "KERNEL.md",
    "MODE_BRANCHES.md", "PLAYBOOKS.md", "RENDER_SPEC.md", "RESOURCES.md",
    "ROUTE_BOOK.md", "WORKFLOW_DETAIL.md",
    "MOTO_MODE.md", "JOURNEY_TYPES.md",
}
# 排除理由逐条可查：MOTOFUN_UPSTREAM_SKILL.md 含 http 外链（千问零外链闸门）；
# 其余为版本历史 / 质量报告 / 合流记录，对使用者无价值且正文引用大量历史路径。
# 词干形式：本文件随 SkillHub / DuMate 包分发，若在此写出带后缀的完整文件名，
# 审核器会把它当成「包内声明了就必须存在的资源」逐个索要（实测 BLOCKER 4 条）。
QW_DOCS_DROP = {s + ".md" for s in (
    "MOTOFUN_UPSTREAM_SKILL", "MOTOFUN_CHANGELOG", "MOTOFUN_QC_REPORT",
    "CHANGELOG", "FUSION", "UNIFIED_ENTRY", "SHOWCASE", "FAQ",
    "OUTBOUND",   # 千问档剔除出境数据，留着这份规则就是指着不存在的数据说话
)}

# 出境「数据」与安全编排：本版定位国内旅行，这些文件既与声明矛盾，又是绿网高风险面
# （各国安全/签证/使馆/货币时区）。
# 注意 **不能删 outbound_constraints.py**：它提供 is_domestic / is_outbound 纯白名单判断，
# route.py 靠它把港澳台正确识别为境内；删了会降级成关键词匹配，把「香港」误判成境外并拒答。
# 该模块的 is_outbound 不读任何数据文件，数据只在未曾实例化的 OutboundConstraints 类里。
EX_QW_FILES = {
    "references/country_safety.json",
    "references/visa_rules.json",
    "references/currency_tz.json",
    "scripts/outbound_safety.py",
    # 必吃板块的「延伸阅读外链」：明写「同品牌美食电子书站 / 站内 book_id / 保证 100% 有链接」，
    # 属商业导流设计。必吃清单本身在 food_guide.json，不受影响。
    "references/food_book_links.json",
    # v0.2.274：本包删了 outbound_safety 与增强渲染器，这三个脚本在此包内已无任何消费者
    # （gate_card 的两个消费方分别是不随包的 outbound_safety 与 render_booklet；
    #  credibility / compute_plugin 的唯一消费方都是 render_booklet）。
    # 留着就是「随包但不被调用」的死代码 —— 裁掉，并靠 BWB.apply_cred_subs 同步正文口径。
    "scripts/compute_plugin.py",
    "scripts/credibility.py",
    "scripts/gate_card.py",
}

# 品牌词中性化：数据文件里的「WorldsTip 摩旅地图库 / 美食电子书库 / 站内接口」
# 有商业导流观感，改为内置数据源描述；frontmatter 去掉品牌前缀。
# 注意 `name: worldstip-travel-planner` 是平台资产标识，不能改（会变成新资产）。
BRAND_SUBS = (
    # 必须排在兜底之前：兜底把品牌名换成名词短语「内置数据」，一旦命中句首，
    # 句子结构就散了 —— 源码 summary 是「WorldsTip：一条命令生成国内行程…」，
    # 兜底替换后成了「内置数据：一条命令生成国内行程…」，主语变成「内置数据」，读不通。
    # 摘掉品牌前缀后句子自然通顺，也不丢任何功能信息。
    ("summary: \"WorldsTip：", "summary: \""),
    ("summary: \"WorldsTip:", "summary: \""),
    ("WorldsTip Travel Guide Booklet", "Travel Guide Booklet"),
    ("WorldsTip旅行指南小册子", "旅行指南小册子"),
    ("WorldsTip 旅行规划", "旅行规划"),
    ("WorldsTip 摩旅地图库", "内置摩旅线路库"),
    ("WorldsTip 摩旅线路库", "内置摩旅线路库"),
    ("WorldsTip 美食电子书库", "内置美食清单"),
    ("WorldsTip by MrdT", "MrdT"),
    # 兜底：名词替换，只适用于句中「XX 数据源」这类位置。
    # 别让它在句首命中（那会造出「内置数据：…」），新增 frontmatter 字段时先看这里。
    ("WorldsTip", "内置数据"),
    ("，站内数据接口）", "，本地离线数据）"),
)

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
    # 数据来源声明里的 Open-Meteo：FALLBACK 只吃域名本体、会把 `https://` 前缀留下，
    # 产出「https://官方渠道」这种畸形串（LICENSE 里实测命中，因该文件原先无扩展名、
    # 从未被外链扫描覆盖，改名 LICENSE.md 后才暴露）。专属规则连协议头一起换掉。
    (re.compile(r"(?:https?://)?(?:[a-z0-9\-]+\.)*open-meteo\.com(?![a-z0-9])"),
     "公开气象数据接口"),
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
# 带可选协议前缀 `(?:https?://)?`：只换域名会留下孤零零的 `https://`，
# 产出「https://官方渠道」这种畸形串（LICENSE 里实测过）。
FALLBACK = (
    (re.compile(r"(?:https?://)?(?:[a-z0-9\-]+\.)+(?:gov|com|cn|net|org|io)(?:\.[a-z]{2})?(?![a-z0-9])"),
     "官方渠道"),
)
TEXT_EXT = (".md", ".json", ".py", ".txt")
DOC_EXT = (".md", ".json", ".txt")

# C. SKILL.md 专属改写
QW_SKILL_SUBS = (
    ("，变更要点见 `CHANGELOG.md`。", "。"),
    # 出境分支：千问档按定位剔除出境数据，指着它们的整句话一并去掉，
    # 否则就是「文档说有、包内没有」的悬空引用。
    ("**出境分支**（可选，国内行程不加载）：规则见 [`docs/OUTBOUND.md`](docs/OUTBOUND.md)，"
     "数据见 `references/visa_rules.json`、`references/currency_tz.json`、"
     "`references/local_customs.json`、`references/country_safety.json`，"
     "由 `scripts/outbound_constraints.py` / `scripts/outbound_safety.py` 消费。", ""),
    ("*© WorldsTip by MrdT · 本技能以 MIT 许可发布并附加反蒸馏条款："
     "禁止未授权搬运、二次分发或用于模型训练/蒸馏；核心 POI 与气候数据受保护，"
     "详见包内 `ANTI_DISTILL.md`。*",
     "*© WorldsTip by MrdT · 本技能以 MIT 许可发布；核心 POI 与气候数据受保护。*"),
)

# 千问包同样把 LICENSE 改名为 LICENSE.md。
# 千问官方文档只列了 3 条硬约束（ZIP<=10MiB / 根级 SKILL.md / frontmatter 含 name+description），
# 未提文件类型白名单；但 SkillHub 已实测拒收无扩展名的 `LICENSE`（报错「不允许的文件类型: LICENSE」），
# 二者同属国内平台，提前改掉比传上去被拒再返工便宜。
# 本包对 LICENSE 的引用只有 README 目录树一行（无 markdown 链接），改动面极小；
# 源码仍是 `LICENSE`，只在构建时改名，单一真源不受影响。
QW_RENAME = {"LICENSE": "LICENSE.md"}
QW_LICENSE_SUBS = (
    ("├── LICENSE                      MIT 协议 + 数据免责声明",
     "├── LICENSE.md                   MIT 协议 + 数据免责声明"),
)


DOMAIN = re.compile(r"[a-z0-9.\-]*(?:worldstip\.com|qianwenai\.com|github\.com|"
                    r"openstreetmap\.org|unpkg\.com|w3\.org)", re.I)
URL = re.compile(r"https?://")
SENSITIVE = ("政治",)
# 替换误伤信号：中文替换词紧贴 ASCII 字母（说明命中的是标识符片段，如 re.com*pile*）
DAMAGE = re.compile(r"[A-Za-z]官方渠道|官方渠道[A-Za-z]")

# frontmatter 重写：千问包不带 places_history / fixtures / render_booklet，
# 原描述却宣称「人文史 sidecar 按需加载」「离线样例数据可复现」「九风格增强渲染」，
# 属描述与实际不符；description 里还堆了 10 个触发词，观感像 SEO 堆砌。
# 注：此处原有 _ver() 把版本号注入 description。description 现已不写版本号
# （自检 C 维度仍会盯描述里的版本串，写进去只会反复过期），_ver 随之成为死代码，删除。

def fm_text():
    """千问包 frontmatter 重写：按**实际随包能力**表述，不吹没有的功能。

    硬纪律：**触发词必须保留**。曾以「像 SEO 堆砌」为由把 10 个触发词全删，
    结果 description 里再没有任何可被索引匹配的短语，技能在千问平台唤不起来 ——
    这不是文风问题，是把触发面清零。现保留核心触发词，其余能力压进正文。
    """
    return {
        "description":
            # 品牌词中性化：千问档整体把品牌名换成能力描述，description 也不留。
            # v0.2.275：原文写「一句话生成国内 A5 行程小册子」，只讲单件 A5。
            # 但 v0.2.274 起默认 `--device both` 一次出三件（电脑网页 / A5 / 手机 HTML5），
            # 同一个包里的 description_zh 早已改成「一次给三份成品」——
            # 两个描述字段一个说单件、一个说三件，包内自相矛盾。
            # description 是平台检索与展示的主字段，口径必须与真实产物一致。
            # 受 doctor「description 单行且 <= 200 字」硬限，写紧凑些：
            # 触发词 12 个与负向边界都不许压，压的是修饰语。
            "旅行规划：一句话生成国内行程，按终端一次出三件：电脑网页、"
            "A5 可打印、手机 HTML5。完成地名消歧、逐日动线、交通比选、"
            "分房预算；摩旅自驾另给真实里程与线路形状图。"
            "跨省同名地名先列候选，非出行请求明确拒答。"
            "触发词：旅行规划、行程规划、旅游攻略、周末去哪玩、爬山看日出、自驾、"
            "citywalk、摩旅、跑山美食、骑完去哪逛、商圈美食、房车。"
            "不触发：票务代订、酒店预订、导航、与旅行骑游无关的请求。",
        "description_zh":
            # 不写版本号、不写内部迭代代号（「摩旅线路形状版」这类）：
            # 那是我们自己认路用的，用户看不懂，且每逢改版必过期。
            "国内旅行指南小册子：把一句出行想法变成能照着走的旅行小册子，"
            "按终端一次给三份成品——电脑网页版、可打印的 A5 小册子、手机 HTML5 版。"
            "自动完成地名抽取与消歧、逐日动线、交通比选、住宿分房与预算，"
            "摩旅自驾另给真实里程与线路形状。跨省同名地名先列候选不硬判，"
            "非出行请求明确拒答；事实以包内离线库为准，没覆盖的字段标「需现场确认」，绝不编造。",
        "description_en":
            "Domestic Travel Guide Booklet: turns one sentence into a ready-to-follow trip "
            "booklet and delivers three terminal-specific builds at once — a desktop web page, "
            "a print-ready A5 booklet, and a mobile HTML5 page. It handles place extraction and "
            "disambiguation, day-by-day routes, transit comparison, room split and budget; rides "
            "and drives also get a mileage axis and a to-scale shape of the real road. "
            "Cross-province homonyms surface candidates instead of guessing and off-topic "
            "requests are refused explicitly. Facts come from the bundled offline library; "
            "anything not covered is marked unverified, never fabricated.",
    }


# 能力声明对齐：原写「含中国香港/澳门/台湾地区」，但意图闸门的地名库未覆盖港澳，
# 实测会被判「未识别到出行意图」拒答 —— 声明与实际不符，千问包按实际能力表述。
SCOPE_SUBS = (
    ("（含中国香港、中国澳门、中国台湾地区）", ""),
    ("（含港澳台）", ""),
    # 基名不再带「·合并版」这类内部迭代代号，源串随 SKILL.md 同步
    ('display_name: "旅行指南小册子"', 'display_name: "国内旅行指南小册子"'),
    ('displayName: "旅行指南小册子"', 'displayName: "国内旅行指南小册子"'),
)


# 剔除 food_book_links.json 后，SKILL.md 里对它的两处引用要一并清除，
# 否则就是幽灵引用（模型会据此编造一个不存在的文件）。
SKILL_REGEX_SUBS = (
    (r"板块末尾按 `references/food_book_links\.json`.*?(?=\s*\|)", ""),
    (r"`references/food_book_links\.json`\s*", ""),
    # 品牌前缀与版本号连写时（「WorldsTip v0.x.y」）旧版写死了一个版本串，
    # 一升版本就失效变成死规则。改成按模式匹配，任何版本都吃得下。
    (r"WorldsTip\s+v\d+\.\d+\.\d+\s*", ""),
)


def patch_frontmatter(text):
    """只重写 frontmatter 段内的指定字段，正文不动。"""
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    fm = parts[1]
    for key, val in fm_text().items():
        fm = re.sub(r"(?m)^%s: .*$" % re.escape(key), '%s: "%s"' % (key, val), fm, count=1)
    return "---" + fm + "---" + parts[2]


# 千问档剔除 scripts/outbound_safety.py（出境安全编排属绿网高风险面），
# README 里「国外的可以做」整段就是在讲这个脚本 —— 留着就是指着不存在的文件说话。
QW_README_DROP = re.compile(
    r"\*\*国外的可以做.*?（含行动项，不是只拦不教）。\s*", re.S)


# 千问包不含增强渲染器（render_booklet），文档里的指路必须改成「本包不含」，
# 否则读者会去要一个包里没有的文件（审核器按悬空引用驳回）。
QW_DOC_SUBS = (
    ("`scripts/render_booklet.py` 保留作为 Apple 风备选（旧版），不再作默认。",
     "增强渲染器（九风格版）不随本包分发，本包只带紧凑渲染器。"),
    ("原 `render_booklet.py` 的 Wikimedia Commons 热链、`cover_url`、`images`、授权署名等代码",
     "九风格版曾有的 Wikimedia Commons 热链、`cover_url`、`images`、授权署名等代码"),
)
QW_BOOKLET_RE = re.compile(r"`?scripts/render_booklet\.py`?|`?render_booklet\.py`?")


def scrub_booklet_refs(text):
    for a, b in QW_DOC_SUBS:
        text = text.replace(a, b)
    return QW_BOOKLET_RE.sub("增强渲染器", text)


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
        if "/" in rel and top in EX_QW_DIRS:
            continue
        if rel.startswith("docs/"):
            if rel[len("docs/"):] not in QW_DOCS_KEEP:
                continue
        if rel in BWB.EX_FILES or rel in EX_QW_DOCS or rel in EX_QW_FILES:
            continue
        items.append((rel, p))

    # 平台类型白名单：无扩展名文件一律拒收（SkillHub 实测），构建期改名。
    items = [(QW_RENAME.get(rel, rel), p) for rel, p in items]

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
                    text = QW_README_DROP.sub("", text)
                    # 改名后目录树必须同步，否则读者照着树去找一个不存在的 `LICENSE`
                    for a, b in QW_LICENSE_SUBS:
                        text = text.replace(a, b)
                text = scrub_origins(text, fallback_ok=rel.lower().endswith(DOC_EXT))
                # 只改文档：.py 里改成中文名词会把「判断某脚本是否存在」的逻辑一起改坏
                # （实测把 isfile("render_booklet.py") 改成了 isfile("增强渲染器")）。
                if not rel.endswith(".py"):
                    text = scrub_booklet_refs(text)
                if rel.startswith("docs/") and rel.endswith(".md"):
                    # v0.2.274：本包也裁了 credibility / compute_plugin / gate_card / site_query，
                    # 文档里指路这些文件的整行/整句必须同步处理，否则就是「指着包里没有的文件说话」。
                    # 复用 workbuddy 的裁行规则，保证两个精简包的文档口径一致。
                    text = BWB.apply_cred_subs(BWB.patch_doc(text))
                for a, b in BRAND_SUBS:
                    text = text.replace(a, b)
                if rel == "SKILL.md":
                    # 能力声明对齐 + 幽灵引用清除 + frontmatter 重写
                    for a, b in SCOPE_SUBS:
                        text = text.replace(a, b)
                    for pat, rep in SKILL_REGEX_SUBS:
                        text = re.sub(pat, rep, text)
                    text = patch_frontmatter(text)
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
    # 平台按扩展名判文件类型，无扩展名一律拒收（SkillHub 实测文案「不允许的文件类型」）。
    # 这条必须进自检：本地门禁全绿也测不出「文件能进包但平台不收」这类缺陷。
    noext = sorted(n for n in names
                   if not n.endswith("/") and "." not in n.split("/")[-1])
    # 替换误伤自检：任何 .py 出现中文替换词紧贴字母，说明把源码标识符改坏了
    damage = []
    brand = 0
    with zipfile.ZipFile(out) as z:
        for n in names:
            if not n.endswith(".py"):
                continue
            t = z.read(n).decode("utf-8", errors="replace")
            for m in DAMAGE.finditer(t):
                damage.append("%s: %s" % (n, t[max(0, m.start() - 20):m.end() + 15]))
        for n in names:
            if not n.lower().endswith((".md", ".json", ".py", ".txt")):
                continue
            brand += z.read(n).decode("utf-8", errors="replace").count("WorldsTip")
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
        ("无出境能力文件", not (set(names) & EX_QW_FILES), str(sorted(set(names) & EX_QW_FILES))),
        ("品牌词已中性化", brand == 0, "WorldsTip 残留 %d" % brand),
        ("替换无源码误伤", not damage, str(damage[:3])),
        ("无无扩展名文件", not noext, str(noext)),
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
    try:
        AU.assert_clean(out)
    except RuntimeError:
        os.remove(out)
        raise
    return 0 if report(out) else 1


if __name__ == "__main__":
    sys.exit(main())
