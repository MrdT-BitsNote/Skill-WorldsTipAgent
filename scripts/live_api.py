#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实 API 实算统一接入层（v0.1.0）。

设计原则（合规 + 不破坏零依赖底线）：
- 仅在配置对应环境变量后启用；未配置或调用失败一律返回 None，上层自动回落到估算值。
- 本文件仅依赖标准库，可被 render_booklet / fetch_weather / compute_plugin 安全 import。
- 所有对外函数返回 (data, source) 二元组，source 用于渲染端「实算✓·来源」徽章，杜绝假徽章。

三个真实数据源：
  1. 地图服务 Web 服务  —— 距离矩阵 / 驾车路径规划（环境变量 MAP_CFG）
  2. 天气服务 API —— 7 天预报（环境变量 WEATHER_CFG）
  3. Open-Meteo            —— 天气（无需授权，作为天气服务的兜底）

环境变量：
  MAP_CFG       地图服务 Web 服务授权配置
  WEATHER_CFG   天气服务授权配置（开发者免费版即可；location 直接用 "经度,纬度"）
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 12

# ── WMO 天气代码 -> 中文描述（Open-Meteo 用）────────────────────
WMO = {
    0: "晴", 1: "大致晴朗", 2: "局部多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "强毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷暴伴冰雹",
}


def _http_json(url: str, retries: int = 2) -> dict | None:
    """标准库 JSON GET，失败返回 None（不抛异常，便于上层回落）。"""
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            if i < retries:
                import time
                time.sleep(0.4 * (i + 1))
    return None


# ───────────────────────────────────────────────────────────────
# 地图服务
# ───────────────────────────────────────────────────────────────
def map_distance_matrix(origins: list, destinations: list, mode: str = "driving") -> list | None:
    """地图服务距离矩阵 v3。origins/destinations: [(lat, lon), ...]。返回 [米]。"""
    cfg = os.environ.get("MAP_CFG")
    if not cfg or not origins or not destinations:
        return None
    o = "|".join(f"{lat},{lon}" for lat, lon in origins)
    d = "|".join(f"{lat},{lon}" for lat, lon in destinations)
    q = urllib.parse.urlencode({"key": cfg, "origins": o, "destinations": d, "type": mode})
    data = _http_json(f"https://restapi.amap.com/v3/distance?{q}")
    if data and data.get("status") == "1" and data.get("results"):
        try:
            return [int(r["distance"]) for r in data["results"]]
        except Exception:  # noqa: BLE001
            return None
    return None


def map_driving(origin: tuple, destination: tuple) -> dict | None:
    """地图服务驾车路径规划 v3，返回 {"distance_km":float, "duration_h":float}。"""
    cfg = os.environ.get("MAP_CFG")
    if not cfg or not origin or not destination:
        return None
    q = urllib.parse.urlencode({
        "key": cfg,
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "extensions": "base", "strategy": "0",
    })
    data = _http_json(f"https://restapi.amap.com/v3/direction/driving?{q}")
    if data and data.get("status") == "1":
        path = (data.get("route") or {}).get("paths", [{}])[0]
        try:
            return {
                "distance_km": round(int(path.get("distance", 0)) / 1000, 1),
                "duration_h": round(int(path.get("duration", 0)) / 3600, 1),
            }
        except Exception:  # noqa: BLE001
            return None
    return None


def map_real_distance(from_coord: tuple, to_coord: tuple) -> tuple:
    """地图服务实算城际里程。返回 (distance_km, duration_h, source) 或 (None, None, None)。"""
    if not (from_coord and to_coord and os.environ.get("MAP_CFG")):
        return None, None, None
    drv = map_driving(from_coord, to_coord)
    if drv:
        return drv["distance_km"], drv["duration_h"], "地图服务"
    dm = map_distance_matrix([from_coord], [to_coord])
    if dm:
        return round(dm[0] / 1000, 1), None, "地图服务"
    return None, None, None


# ───────────────────────────────────────────────────────────────
# 天气服务
# ───────────────────────────────────────────────────────────────
def weather_service(lat: float, lon: float, days: int = 7) -> dict | None:
    """天气服务 7 天预报。返回归一化 dict（同 open_meteo 输出结构）或 None。

    免费开发者版 location 直接用 "经度,纬度" 即可；precip_prob 在免费 7d 接口
    不返回，置 None 并如实标注。
    """
    cfg = os.environ.get("WEATHER_CFG")
    if not cfg:
        return None
    days = max(1, min(7, days))
    loc = f"{lon:.4f},{lat:.4f}"
    data = _http_json(
        "https://devapi.qweather.com/v7/weather/7d?"
        + urllib.parse.urlencode({"location": loc, "key": cfg})
    )
    if not data or data.get("code") != "200":
        return None
    out_days = []
    for d in (data.get("daily") or [])[:days]:
        out_days.append({
            "date": d.get("fxDate", ""),
            "wmo_text": d.get("textDay", ""),
            "t_min": _to_num(d.get("tempMin")),
            "t_max": _to_num(d.get("tempMax")),
            "precip_mm": _to_num(d.get("precip")) or 0,
            "precip_prob": None,  # 免费 7d 接口不含降水概率
            "wind_kmh": _to_num(d.get("windSpeedDay")),
        })
    if not out_days:
        return None
    return {"days": out_days, "source": "天气服务"}


# ───────────────────────────────────────────────────────────────
# Open-Meteo（免授权兜底）
# ───────────────────────────────────────────────────────────────
def open_meteo(lat: float, lon: float, days: int = 7) -> dict | None:
    """Open-Meteo 实况+预报（无需 API key）。返回与 weather_service 同构的归一化 dict。"""
    days = max(1, min(16, days))
    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
        "timezone": "Asia/Shanghai",
        "forecast_days": days,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    data = _http_json(url)
    if not data:
        return None
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    if not times:
        return None
    out_days = []
    for i, day in enumerate(times):
        code = daily["weather_code"][i]
        out_days.append({
            "date": day,
            "wmo_text": WMO.get(code, f"代码{code}"),
            "t_min": _to_num(daily["temperature_2m_min"][i]),
            "t_max": _to_num(daily["temperature_2m_max"][i]),
            "precip_mm": _to_num(daily.get("precipitation_sum", [0] * len(times))[i]) or 0,
            "precip_prob": _to_num((daily.get("precipitation_probability_max") or [None] * len(times))[i]),
            "wind_kmh": _to_num((daily.get("wind_speed_10m_max") or [None] * len(times))[i]),
        })
    return {"days": out_days, "source": "Open-Meteo"}


def weather_unified(lat: float, lon: float, days: int = 7) -> tuple:
    """天气统一入口：优先天气服务（有 key），否则 Open-Meteo。

    返回 (days_list, source) 或 (None, None)。
    """
    # 天气服务优先
    qw = weather_service(lat, lon, days)
    if qw:
        return qw["days"], "天气服务"
    om = open_meteo(lat, lon, days)
    if om:
        return om["days"], "Open-Meteo"
    return None, None


def _to_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
