# -*- coding: utf-8 -*-
"""test_guide_list.py — 攻略清单校验器回归测试（v0.1.27）。

锁死纪律：
- 必填字段缺失 / 日期非法 / 未来日期 / 非法 URL → 拒绝
- 票务域名与交易路径 → 拒绝（合规红线）
- 追踪参数归一化后去重
- match 降序 → confidence 降序 → 日期降序
- >30 天临近过期 / >90 天参考价值待定 标注
- 空输入不崩；--strict 有错即退出码 1
Windows 控制台友好：只用 ASCII 打印。
"""
import io
import json
import os
import subprocess
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guide_list as G  # noqa: E402

TODAY = date.today()
D30 = (TODAY - timedelta(days=45)).isoformat()   # 临近过期
D90 = (TODAY - timedelta(days=120)).isoformat()  # 参考价值待定
DFRESH = TODAY.isoformat()

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


def entry(**kw):
    base = {
        "title": "张家界三天两晚徒步攻略",
        "url": "https://example.com/a/zhangjiajie-hike",
        "source": "某问答社区用户",
        "source_type": "ugc_qa",
        "summary": "含袁家界→天子山步行时间与省钱路线",
        "verified_on": DFRESH,
        "confidence": "verified",
        "match": 0.8,
    }
    base.update(kw)
    return base


# --- 1) 合法条目通过 -------------------------------------------------------
check("valid entry passes", G.validate_entry(entry(), 1) == [])

# --- 2) 必填缺失 -----------------------------------------------------------
for k in ("title", "url", "source", "verified_on"):
    e = entry()
    del e[k]
    check("missing %s rejected" % k, any(k in m for m in G.validate_entry(e, 1)))

# --- 3) 日期合法性 ---------------------------------------------------------
check("bad date format rejected", G.validate_entry(entry(verified_on="2026/10/01"), 1))
check("future date rejected", G.validate_entry(entry(verified_on="2099-01-01"), 1))
check("empty date rejected", G.validate_entry(entry(verified_on=""), 1))

# --- 4) URL 合法性 ---------------------------------------------------------
check("relative url rejected", G.validate_entry(entry(url="/guide/abc"), 1))
check("ftp url rejected", G.validate_entry(entry(url="ftp://x.com/a"), 1))

# --- 5) 合规红线：票务/交易链接 --------------------------------------------
ok1, why1 = G.check_url("https://www.ticket.example.cn/item.html?id=1")
check("ticket domain blocked", not ok1 and "票务" in why1)
ok2, why2 = G.check_url("https://travel.example.com/checkout/step1")
check("checkout path blocked", not ok2 and "交易" in why2)
ok3, why3 = G.check_url("https://shop.example.com/order/confirm?book=1")
check("order path blocked", not ok3)
ok4, why4 = G.check_url("https://news.example.com/p/zhangjiajie-guide.html")
check("info article allowed", ok4)

# --- 6) 去重（utm 归一化） -------------------------------------------------
a = entry(url="https://example.com/a/x?utm_source=social")
b = entry(url="https://www.example.com/a/x/", match=0.9)
dd = G.dedup([a, b])
check("dedup by normalized url", len(dd) == 1)
check("dedup keeps higher match", dd[0]["match"] == 0.9)

# --- 7) 排序：match > confidence > date ------------------------------------
s = G.sort_entries([
    entry(title="low", match=0.2, url="https://e.com/1"),
    entry(title="high-match", match=0.9, url="https://e.com/2"),
    entry(title="same-match-official", match=0.9, url="https://e.com/3",
          confidence="official", verified_on=D90),
    entry(title="same-match-verified", match=0.9, url="https://e.com/4",
          confidence="verified", verified_on=D30),
])
titles = [e["title"] for e in s]
check("sort: low match last", titles[-1] == "low")
check("sort: official first even if older date", titles[0] == "same-match-official")
check("sort: fresher verified before older verified",
      titles.index("high-match") < titles.index("same-match-verified"))

# --- 8) 时效标注 -----------------------------------------------------------
check("stale >30d flagged", "临近过期" in G.staleness(G._parse_date(D30)))
check("stale >90d flagged", "参考价值待定" in G.staleness(G._parse_date(D90)))
check("fresh not flagged", G.staleness(G._parse_date(DFRESH)) == "")

# --- 9) 渲染 ---------------------------------------------------------------
md = G.render_md([entry(), entry(title="官方页", url="https://gov.example.cn/2",
                                 source="景区官网", source_type="official",
                                 confidence="official", verified_on=D90, match=0.95)])
check("md has header row", "| # |" in md and "| 来源 |" in md)
check("md has link", "](https://example.com/a/zhangjiajie-hike)" in md)
check("md has badge", "`多源印证`" in md and "`官方`" in md)
check("md has >90d flag", "参考价值待定" in md)
check("md escapes pipe in title",
      "\\|" in G.render_md([entry(title="A|B")]))
check("empty input renders empty", G.render_md([]) == "")

# --- 10) CLI 端到端 --------------------------------------------------------
tmp = os.path.join(HERE, "_gl_test_tmp.json")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump([entry(), entry(url="https://ticket.example.cn/x")], f)
r1 = subprocess.run([sys.executable, os.path.join(HERE, "guide_list.py"), tmp],
                    capture_output=True, text=True, encoding="utf-8")
check("cli outputs valid row only", "zhangjiajie-hike" in r1.stdout
      and "1 条有效攻略" in r1.stderr)
r2 = subprocess.run([sys.executable, os.path.join(HERE, "guide_list.py"), tmp, "--strict"],
                    capture_output=True, text=True, encoding="utf-8")
check("cli --strict exit 1 on rejection", r2.returncode == 1)
with open(tmp, "w", encoding="utf-8") as f:
    json.dump([], f)
r3 = subprocess.run([sys.executable, os.path.join(HERE, "guide_list.py"), tmp],
                    capture_output=True, text=True, encoding="utf-8")
check("cli empty input no crash", r3.returncode == 0 and r3.stdout.strip() == "")
os.remove(tmp)

print("\ntest_guide_list: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
