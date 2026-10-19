# -*- coding: utf-8 -*-
"""test_guide_digest.py — 攻略研读沉淀校验器回归测试（v0.1.28）。

锁死纪律：
- 三元组（fact/source/verified_on/confidence）缺一即拒；unknown 置信拒绝进册
- 日期非法/未来日期拒绝；fact 超长（疑似照搬原文）拒绝
- category 白名单；category → kind 映射正确
- 同事实同来源去重；同事实多来源合并升级 verified + multi
- recency 分桶；volatile>30d / 体验>90d 标 needs_recheck
- 输出结构兼容既有 ugc 键；--merge 去重合并；空输入不崩；--strict 退出码
Windows 控制台友好：只用 ASCII 打印。
"""
import json
import os
import subprocess
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guide_digest as D  # noqa: E402

TODAY = date.today()
D_FRESH = TODAY.isoformat()
D_45 = (TODAY - timedelta(days=45)).isoformat()
D_120 = (TODAY - timedelta(days=120)).isoformat()

ok = 0
fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print("ok   -", name)
    else:
        fail += 1
        print("FAIL -", name)


def fact(**kw):
    base = {
        "fact": "岳阳楼门票 70 元，学生半价，需提前在公众号预约",
        "category": "ticket",
        "spot": "岳阳楼",
        "source": "岳阳楼景区公众号",
        "source_type": "official",
        "verified_on": D_FRESH,
        "confidence": "official",
    }
    base.update(kw)
    return base


# --- 1) 合法条目 -----------------------------------------------------------
check("valid fact passes", D.validate_fact(fact(), 1) == [])

# --- 2) 三元组缺失 ---------------------------------------------------------
for k in ("fact", "source", "verified_on", "confidence"):
    e = fact()
    del e[k]
    check("missing %s rejected" % k, any(k in m for m in D.validate_fact(e, 1)))

# --- 3) 纪律字段 -----------------------------------------------------------
check("unknown confidence rejected (gray-light not in booklet)",
      any("unknown" in m for m in D.validate_fact(fact(confidence="unknown"), 1)))
check("bad category rejected", D.validate_fact(fact(category="mood"), 1))
check("bad date rejected", D.validate_fact(fact(verified_on="2026/10/01"), 1))
check("future date rejected", D.validate_fact(fact(verified_on="2099-01-01"), 1))
check("overlong fact (copy-paste guard) rejected",
      D.validate_fact(fact(fact="啊" * 200), 1))

# --- 4) category → kind 映射 ----------------------------------------------
check("ticket maps to 价格", D.CATEGORY_KIND["ticket"] == "价格")
check("pitfall maps to 踩坑", D.CATEGORY_KIND["pitfall"] == "踩坑")
check("photo maps to 体验", D.CATEGORY_KIND["photo"] == "体验")

# --- 5) 去重与合并升级 -----------------------------------------------------
m = D.merge_facts([
    fact(source="来源A", confidence="single"),
    fact(source="来源A", confidence="single"),  # 同事实同来源 → 去重
    fact(source="来源B", confidence="single"),   # 第二个独立来源 → 合并升级
])
check("dedup same fact+source", len(m) == 1)
check("multi-source upgraded to verified", m[0]["confidence"] == "检索" and m[0]["multi"])
check("sources joined", "来源A" in m[0]["source"] and "来源B" in m[0]["source"])
check("official not downgraded by merge",
      D.merge_facts([fact(source="官网"), fact(source="某评论", confidence="single")])[0]["src"] == "官方")

# --- 6) recency 与时效 -----------------------------------------------------
check("recency fresh = 近6月", D._recency(D._parse_date(D_FRESH)) == "近6月")
check("recency 120d = 近6月 (<=183d)", D._recency(D._parse_date(D_120)) == "近6月")
check("recency 200d = 近1年",
      D._recency(D._parse_date((TODAY - timedelta(days=200)).isoformat())) == "近1年")
check("recency 400d = 更早",
      D._recency(D._parse_date((TODAY - timedelta(days=400)).isoformat())) == "更早")
check("volatile >30d needs recheck", D._needs_recheck(D._parse_date(D_45), "ticket"))
check("volatile fresh no recheck", not D._needs_recheck(D._parse_date(D_FRESH), "ticket"))
check("experience 45d no recheck", not D._needs_recheck(D._parse_date(D_45), "food"))
check("experience >90d needs recheck", D._needs_recheck(D._parse_date(D_120), "food"))

# --- 7) 输出结构兼容既有 ugc 键 -------------------------------------------
u = m[0]
for k in ("kind", "where", "text", "src", "source", "recency", "verified_on", "confidence"):
    check("output has ugc key %s" % k, k in u)
check("output carries category for grouping", u.get("category") == "ticket")
check("latest verified_on kept",
      D.merge_facts([fact(verified_on=D_45), fact(source="B", verified_on=D_FRESH)])[0]["verified_on"] == D_FRESH)

# --- 8) CLI 端到端 ---------------------------------------------------------
tmp = os.path.join(HERE, "_gd_test_tmp.json")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump([fact(), fact(category="pitfall", fact="古城内停车位少，建议停外围",
                            source="某点评页面", source_type="ugc_review",
                            confidence="single", verified_on=D_45),
               dict(fact(), confidence="unknown")], f)
r1 = subprocess.run([sys.executable, os.path.join(HERE, "guide_digest.py"), tmp],
                    capture_output=True, text=True, encoding="utf-8")
try:
    out = json.loads(r1.stdout)
except ValueError:
    out = None
check("cli outputs 2 valid ugc entries", out is not None and len(out) == 2)
check("cli stderr reports rejection", "unknown" in r1.stderr and "拒绝" in r1.stderr)
r2 = subprocess.run([sys.executable, os.path.join(HERE, "guide_digest.py"), tmp, "--strict"],
                    capture_output=True, text=True, encoding="utf-8")
check("cli --strict exit 1 on rejection", r2.returncode == 1)

# --merge 行为
rj = os.path.join(HERE, "_gd_test_research.json")
with open(rj, "w", encoding="utf-8") as f:
    json.dump({"ugc": [{"kind": "贴士", "text": "旧条目", "source": "x",
                        "verified_on": D_FRESH, "confidence": "检索"}]}, f)
r3 = subprocess.run([sys.executable, os.path.join(HERE, "guide_digest.py"), tmp, "--merge", rj],
                    capture_output=True, text=True, encoding="utf-8")
research = json.load(open(rj, encoding="utf-8"))
check("merge appends without dropping existing", len(research["ugc"]) == 3)
# 再跑一次：同事实不应重复追加
subprocess.run([sys.executable, os.path.join(HERE, "guide_digest.py"), tmp, "--merge", rj],
               capture_output=True, text=True, encoding="utf-8")
research2 = json.load(open(rj, encoding="utf-8"))
check("merge dedups same fact text", len(research2["ugc"]) == 3)

with open(tmp, "w", encoding="utf-8") as f:
    json.dump([], f)
r4 = subprocess.run([sys.executable, os.path.join(HERE, "guide_digest.py"), tmp],
                    capture_output=True, text=True, encoding="utf-8")
check("cli empty input no crash", r4.returncode == 0 and r4.stdout.strip() == "")
os.remove(tmp)
os.remove(rj)

print("\ntest_guide_digest: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
