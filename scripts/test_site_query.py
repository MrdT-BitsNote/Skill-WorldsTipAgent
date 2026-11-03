#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_site_query.py — 站点数据接入离线测试（预置缓存 fixture，全程不联网）。"""
import copy
import json
import sys
import tempfile
import urllib.error
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_query as S

ok = fail = 0


def check(cond, name):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS {name}")
    else:
        fail += 1
        print(f"  FAIL {name}")


TMP = Path(tempfile.mkdtemp(prefix="wt_site_test_"))

MOTO_INDEX = {
    "generated": "2026-10-24", "totalRoutes": 2, "totalWaypoints": 4, "totalCities": 2,
    "provinces": [{"name": "湖南省", "code": "hunan", "file": "provinces/hunan.json",
                   "routes": 2, "cities": 2, "sizeKB": 10}],
}
MOTO_HUNAN = {
    "province": "湖南省", "code": "hunan",
    "cities": [{"slug": "changsha", "name": "长沙", "routes": 1}],
    "routes": [
        {"id": "taifushan", "n": "临澧太浮山跑山线", "t": "攻山压弯", "d": 88, "days": 1,
         "h": ["山道", "云海"], "w": [[29.0, 111.0]], "wn": ["集合点"],
         "city": "常德", "citySlug": "changde", "url": "/hunan/routes/taifushan/",
         "cs": "verified", "srcs": 0},
        {"id": "hunan-loop1", "n": "湘中环线", "t": "长途环线", "d": 620, "days": 4,
         "h": ["环线"], "w": [[28.0, 112.0]], "wn": ["长沙"],
         "city": "湖南省", "citySlug": "loops", "url": "/hunan/routes/hunan-loop1/",
         "cs": "computed", "srcs": 0},
    ],
}
FUN_DATA = {
    "meta": {"name": "FUN", "version": "v0.9.0", "generated": "2026-11-01"},
    "stats": {"provinces": 32, "cities": 389, "poi_total": 328980},
    "cities": [{
        "city": "岳阳市", "province": "湖南省", "adcode": "430600",
        "poi_total": 900, "district_count": 3, "updated": "2026-10-30",
        "grades": {"S": 1, "A": 1, "B": 1, "C": 0},
        "districts": [
            {"name": "步行街商圈", "grade": "A", "total": 65.0, "rating": 4.2, "poi": 120,
             "food": 40, "leisure": 50, "carrier": "商业街"},
            {"name": "南湖商圈", "grade": "S", "total": 75.5, "rating": 4.4, "poi": 150,
             "food": 60, "leisure": 60, "carrier": "综合体"},
        ],
        "food": [{"mark": "✅A-", "name": "示例烧烤", "sub": "烧烤", "type": "餐饮服务;烧烤",
                  "rating": 4.5, "avg": 55, "addr": "岳阳楼区某某路", "img": ""}],
        "leisure": {"subcats": [{"name": "KTV", "count": 3}],
                    "list": [{"name": "示例KTV", "rating": 4.0, "avg": 80, "addr": "某路"}]},
    }],
}


def put_cache(url, obj):
    S._cache_path(url, TMP).parent.mkdir(parents=True, exist_ok=True)
    S._cache_path(url, TMP).write_bytes(json.dumps(obj, ensure_ascii=False).encode())


put_cache(S.SPEC["moto"]["endpoints"]["index"], MOTO_INDEX)
put_cache(S.SPEC["moto"]["home"] + "/map-data/provinces/hunan.json", MOTO_HUNAN)
put_cache(S.SPEC["fun"]["endpoints"]["data"], FUN_DATA)

OFF = dict(cache_dir=TMP, offline=True)

print("== 1. 省份解析（中文/拼音/带省字） ==")
for q in ("湖南", "湖南省", "hunan"):
    r = S.moto_routes(q, **OFF)
    check(r["province"] == "湖南省" and r["total"] == 2, f"moto 省份解析: {q}")

print("== 2. 路线过滤与口径 ==")
r = S.moto_routes("湖南", city="常德", **OFF)
check(r["total"] == 1 and r["routes"][0]["name"] == "临澧太浮山跑山线", "按城市过滤")
r = S.moto_routes("湖南", rtype="长途环线", **OFF)
check(r["total"] == 1 and r["routes"][0]["cs"] == "computed", "按类型过滤")
r = S.moto_routes("湖南", **OFF)
check(r["routes"][0]["cs"] == "verified" and r["routes"][-1]["cs"] == "computed", "verified 排在 computed 前")
comp = [x for x in r["routes"] if x["cs"] == "computed"][0]
check("非实测" in comp["credibility"], "computed 明确标注『非实测』")
check(comp["url"].startswith("https://moto.worldstip.com/"), "详情页直链由 url 字段拼接（不手拼）")
check(r["generated"] == "2026-10-24", "来源日期戳透传")

print("== 3. FUN 城市与板块 ==")
c = S.fun_city("岳阳", **OFF)
check(c["city"] == "岳阳市", "城市名模糊匹配（不带市）")
check(c["_meta_generated"] == "2026-11-01" and c["updated"] == "2026-10-30", "采集/生成日期戳透传")
d = S.fun_section(c, "districts")
check(d[0]["name"] == "南湖商圈", "商圈按总分降序")
d_s = S.fun_section(c, "districts", grade="s")
check(len(d_s) == 1 and d_s[0]["grade"] == "S", "评级过滤（大小写不敏感）")
check(len(S.fun_section(c, "food")) == 1, "美食板块")
check(S.fun_section(c, "leisure")[0]["name"] == "示例KTV", "休闲板块 list 提取")
check(len(S.fun_section(c, "hotels")) == 0, "空板块安全返回")

print("== 4. 降级与边界 ==")
try:
    S.moto_routes("湖南", cache_dir=TMP / "empty", offline=True)
    check(False, "离线无缓存应抛 SiteUnavailable")
except S.SiteUnavailable:
    check(True, "离线无缓存 → SiteUnavailable（不编造）")
try:
    S.fun_city("不存在市", **OFF)
    check(False, "未收录城市应 SystemExit")
except SystemExit as e:
    check("未收录 ≠ 该城没有" in str(e), "未收录城市提示含样本边界纪律")
s = S.fun_stats(**OFF)
check(s["stats"]["cities"] == 389 and s["meta"]["version"] == "v0.9.0", "stats 离线回退全量缓存")
check(s["source"] == S.SPEC["fun"]["home"] and "freshness" in s and "analysis" in s, "stats 同样带来源/时效/分析")
blk = S.extract_json_block('{"meta":{"a":1},"stats":{"cities":389,"grades":{"S":231}},"x":', "stats")
check(blk["cities"] == 389 and blk["grades"]["S"] == 231, "Range 首段 stats 花括号配平提取")

print("== 5. 规格文件自洽 ==")
check(S.SPEC["coordinate_system"] == "GCJ-02", "坐标系声明 GCJ-02")
check(S.SPEC["common_policy"]["timeout_seconds"] > 0 and S.SPEC["common_policy"]["retries"] >= 1, "超时/重试已声明")

print("== 6. 分析输出与时效纯函数 ==")
check(r["analysis"]["credibility_counts"] == {"verified": 1, "computed": 1}, "moto 可信度计数")
check(r["analysis"]["distance_km_total"] == 708 and r["analysis"]["distance_km_avg"] == 354, "moto 里程统计仅基于筛选结果")
check(S.freshness("2026-10-01", 90, today=date(2026, 11, 4))["status"] == "current", "90 天内标在复核期")
check(S.freshness("2026-01-01", 90, today=date(2026, 11, 4))["status"] == "stale", "超 90 天标待复核")
check(S.freshness("bad-date", 90, today=date(2026, 11, 4))["status"] == "unknown", "异常日期不猜测")
fa = S.fun_analysis(c, "food", [{"rating": 4.0}, {"rating": None}, {}])
check(fa["rating_avg"] == 4.0 and fa["unrated_count"] == 2, "FUN 无评分不计 0、不进均值")

print("== 7. 城市歧义与网络错误分类 ==")
TMP2 = Path(tempfile.mkdtemp(prefix="wt_site_ambig_"))
ambiguous = copy.deepcopy(FUN_DATA)
ambiguous["cities"].append(dict(ambiguous["cities"][0], province="测试省二"))
S._cache_path(S.SPEC["fun"]["endpoints"]["data"], TMP2).write_bytes(json.dumps(ambiguous, ensure_ascii=False).encode())
try:
    S.fun_city("岳阳", cache_dir=TMP2, offline=True)
    check(False, "同名城市应要求消歧")
except SystemExit as e:
    check("有歧义" in str(e) and "测试省二" in str(e), "同名城市列候选，不默认取第一条")
check(not S._retryable(urllib.error.HTTPError("https://x", 404, "not found", {}, None)), "404 不重试")
check(S._retryable(urllib.error.HTTPError("https://x", 500, "server", {}, None)), "500 可重试")
check(S._retryable(urllib.error.URLError("timeout")), "网络错误可重试")
check(not S._retryable(ValueError("bad json")), "解析/输入错误不重试")
url404 = "https://fun.worldstip.com/not-found.json"
err404 = urllib.error.HTTPError(url404, 404, "not found", {}, None)
with patch.object(S.urllib.request, "urlopen", side_effect=err404) as mocked:
    try:
        S.fetch(url404, cache_dir=TMP / "none", refresh=True)
        check(False, "404 无缓存应报不可用")
    except S.SiteUnavailable:
        check(mocked.call_count == 1, "404 只请求一次后降级")
err500 = urllib.error.HTTPError(S.SPEC["moto"]["endpoints"]["index"], 500, "server", {}, None)
with patch.object(S.urllib.request, "urlopen", side_effect=err500) as mocked, patch.object(S.time, "sleep"):
    body = S.fetch(S.SPEC["moto"]["endpoints"]["index"], cache_dir=TMP, refresh=True)
check(mocked.call_count == S.RETRIES + 1 and json.loads(body)["totalRoutes"] == 2, "500 重试后降级已有缓存")
try:
    S._limit("101")
    check(False, "limit 超界应拒绝")
except Exception:
    check(True, "limit 超界拒绝，避免过量输出")

class _RangeIgnoredResponse:
    status = 200
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n=-1):
        raw = json.dumps(FUN_DATA, ensure_ascii=False).encode()
        return raw if n is None or n < 0 else raw[:n]

range_cache = TMP / "range_fallback"
with patch.object(S.urllib.request, "urlopen", side_effect=lambda *a, **k: _RangeIgnoredResponse()) as mocked:
    sr = S.fun_stats(cache_dir=range_cache)
check(mocked.call_count == 2 and sr["stats"]["cities"] == 389, "Range 被忽略时回退受保护的全量 fetch")
check(S._cache_path(S.SPEC["fun"]["endpoints"]["data"], range_cache).exists(), "Range 回退写缓存，不另开无缓存通道")

print(f"\ntest_site_query: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
