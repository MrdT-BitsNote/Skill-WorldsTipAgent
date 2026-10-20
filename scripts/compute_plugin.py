#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可选实算插件（v0.1.0）。

设计原则：不破坏零依赖底线。
- 仅在配置环境变量后启用；无 Key 或调用失败一律返回 None，渲染器自动回落到估算值并标注「估算ⓘ」。
- 真实距离/路径统一走 live_api（地图服务 MAP_SERVICE_KEY）；本文件只负责把实算结果注入 transit 并打来源标记。

环境变量：
  MAP_SERVICE_KEY       地图服务 Web 服务 Key（距离矩阵 / 驾车路径规划）
  RAIL_PROXY_URL 自建 12306 查询代理地址（12306 无官方开放 API，需自建或第三方服务）

用法（在调用 render_booklet.py 前设置环境变量）：
  export MAP_SERVICE_KEY=你的地图服务Key
  python render_booklet.py --plan plan.json --transit transit.json --compute map --out book.html
"""
import json
import os
import urllib.parse
import urllib.request

# 地图服务/天气服务/Open-Meteo 真实数据源统一入口
from live_api import map_distance_matrix, map_driving  # noqa: E402

_TIMEOUT = 12


def _http_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def rail_12306(from_station: str, to_station: str, date: str = "") -> dict | None:
    """12306 票价：12306 无官方开放 API，需自建代理（RAIL_PROXY_URL）。返回代理原始 JSON。

    实测(2026-10): 12306 官方 leftTicket 需 Cookie/session 初始化, 无登录态直接请求必然失败;
    第三方票务平台 H5 车次接口列表恒为空; 第三方机票接口 Forbidden。
    故票价实算不可行, 必须回落估算并提示用户以官方为准。
    """
    url = os.environ.get("RAIL_PROXY_URL")
    if not url or not from_station or not to_station:
        return None
    q = urllib.parse.urlencode({"from": from_station, "to": to_station, "date": date})
    return _http_json(f"{url}?{q}")


def enrich_transit(transit: dict, coord_lookup: dict | None = None,
                   compute_mode: str = "map") -> tuple:
    """给 transit 注入实算距离/票价。

    compute_mode:
      "map"  → 地图服务距离矩阵 + 驾车路径（需 MAP_SERVICE_KEY）
      "12306" → 12306 票价（需 RAIL_PROXY_URL 自建代理）
      "none"  → 不启用，原样返回
    返回 (transit, computed_bool)。computed 仅在地图服务/代理真正返回数据时置 True，
    渲染端据此显示「实算✓·地图服务」而非「估算ⓘ」，杜绝假徽章。
    """
    if not isinstance(transit, dict) or compute_mode in (None, "none"):
        return transit, False
    coord_lookup = coord_lookup or {}
    computed = False
    out = dict(transit)

    frm_c = transit.get("from_coord")
    to_c = transit.get("to_coord")
    # 若 transit 未直接给坐标，尝试用城市名从 coord_lookup 解析
    if (not frm_c or not to_c) and coord_lookup:
        fc = coord_lookup.get(transit.get("from", ""))
        tc = coord_lookup.get(transit.get("to", ""))
        if fc and tc:
            frm_c, to_c = fc, tc

    if compute_mode in ("map", "12306") and frm_c and to_c:
        dm = map_distance_matrix([frm_c], [to_c])
        if dm:
            out["distance_km"] = round(dm[0] / 1000)
            out["distance_source"] = "地图服务"
            computed = True
        drv = map_driving(frm_c, to_c)
        if drv:
            out["drive_distance_km"] = drv["distance_km"]
            out["drive_hours"] = drv["duration_h"]
            out["distance_source"] = "地图服务"
            computed = True

    if compute_mode in ("map", "12306") and os.environ.get("RAIL_PROXY_URL"):
        rail = rail_12306(transit.get("from_station", ""), transit.get("to_station", ""),
                         transit.get("date", ""))
        if rail:
            out["rail"] = rail
            out["rail_source"] = "12306-proxy"
            computed = True

    if computed:
        out["computed"] = True
    return out, computed
