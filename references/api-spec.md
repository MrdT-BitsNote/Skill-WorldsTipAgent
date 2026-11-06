# 数据接口规范（api-spec）

> 两个数据源均为**只读静态 JSON**，无鉴权、无频控、无跨域限制、允许 CDN 长缓存。
> 全部字段口径来自 2026-11-04 对线上数据的实测核验，非文档推测。

## A. moto.worldstip.com — 摩托骑行路线

### A1. 全国索引

```
GET https://moto.worldstip.com/map-data/index.json
```

实测 200，5280 bytes。`generated` 为数据构建日期，客户端应缓存此文件。

| 字段 | 类型 | 说明 |
|---|---|---|
| `generated` | string | 数据日期，如 `2026-10-24` |
| `totalRoutes` | number | 路线总数（实测 1713） |
| `totalWaypoints` | number | 途经点总数（实测 5022） |
| `totalCities` | number | 覆盖城市数（实测 360） |
| `provinces[]` | array | 31 个省份条目 |
| `provinces[].name` | string | 省份中文全称，如 `湖南省` |
| `provinces[].code` | string | 省份拼音，如 `hunan` |
| `provinces[].file` | string | 数据包相对路径，如 `provinces/hunan.json` |
| `provinces[].routes` | number | 该省路线数 |
| `provinces[].cities` | number | 该省城市数 |
| `provinces[].sizeKB` | number | 数据包大小（19–1934 KB） |

> **加载纪律**：必须用索引返回的 `file` 拼 URL，不要凭 code 硬拼（虽当前两者一致，但索引是权威源）。

### A2. 省份数据包

```
GET https://moto.worldstip.com/map-data/provinces/{code}.json
```

实测湖南省 201 条路线 / 14 城市；青海省 24 条路线 / 8 城市。顶层：`{ province, code, cities[], routes[] }`。

#### `cities[]`

| 字段 | 类型 | 说明 |
|---|---|---|
| `slug` | string | 城市 slug，如 `hainan_zhou` |
| `name` | string | 中文名，**无政区后缀**，如 `海南`、`常德` |
| `routes` | number | 该城市市区周边路线数 |

#### `routes[]`（实测键集合）

`c, city, citySlug, cs, d, days, h, id, n, p, srcs, t, url, w, wn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 路线唯一 ID，如 `taifushan`、`haixi-r1`、`{prov}-loop{n}` |
| `n` | string | 路线名称，如 `临澧太浮山"沅澧名山"跑山线` |
| `t` | string | 类型：攻山压弯 / 山林湖泊 / 文化漫游 / 咖啡驿站 / 近郊休闲 / 长途环线 / 休闲骑游 / 弯道路段 / 人文古迹 / 休闲骑行 |
| `d` | number | 里程（公里） |
| `days` | number | 建议天数（每 200km 记 1 天，市区周边线恒为 1） |
| `h` | string[] | 亮点标签，最多 4 条 |
| `c` | string | 省份主题色 HEX，供地图渲染 |
| `p` | `[lat,lng][]` | 骑行轨迹 polyline，**GCJ-02**；每 3 点取 1 抽稀，坐标 4 位小数，单条最多 3634 点 |
| `w` | `[lat,lng][]` | 关键途经点坐标，GCJ-02 |
| `wn` | string[] | 途经点**景点名称**，与 `w` 一一对应；`w[0]` 恒为集合点/市政府。**注意：`wn` 是景点名，不是城市名** |
| `city` | string | 所属城市中文名，**无后缀**；长途环线存的是**省名** |
| `citySlug` | string | 城市 slug；长途环线恒为 `loops` |
| `url` | string | 站内详情页路径。湖南走 `/routes/{id}/`，其余省份走 `/{code}/routes/{id}/` |
| `cs` | string | 文案状态：`verified`（人工撰写 + 高德 POI 核验）/ `reviewed`（改写自公开资料并附来源）/ `computed`（算法生成，**全部长途环线**） |
| `srcs` | number | 引用来源条数；`reviewed` 线路详情页展示出处 |

> **`wn` 的坑**：实测 `['常德诗墙公园', '太浮山', '宣鉴禅寺']` 是景点名。原型曾把它们逐个拿去 fun 城市库查，全部落空。正确做法：只用 `city` 字段做城市联动，`wn` 作为景点展示。

## B. fun.worldstip.com — 城市生活数据

### B1. 全量单文件

```
GET https://fun.worldstip.com/data.json       # 40.1 MB 明文 / 约 9.4 MB gzip（实测 3.9s）
GET https://fun.worldstip.com/data.md        # 32.1 MB 人类可读版
```

支持 `Range: bytes=0-8191` 取首段拿 `meta` + `stats`（实测返回 206）。顶层：`meta, stats, provinces[], cities[], food_top[], districts_top[]`。

| 顶层 | 说明 |
|---|---|
| `meta` | `name / version(v0.9.0) / generated(2026-10-24 20:41) / home / source / files / schema` |
| `stats` | `provinces=32, cities=389, poi_total=328980, districts_total=5534, grades{S:180,A:523,B:1945,C:2886}` |
| `provinces[]` | 32 条省级汇总：`province, cities, poi, districts, grades, page` |
| `cities[]` | **389 城全量档案**，字段见下 |
| `food_top[]` | 全国美食榜 800 |
| `districts_top[]` | S/A 商圈榜（实测 703，`meta.schema` 称最多 1000） |

### B2. `cities[]` 单城档案（实测键集合）

`adcode, assoc, city, credibility, district_count, districts, external, food, grades, hotels, kids, leisure, malls, overview, page, poi_total, province, queries, specialties, updated, waves, xiaocan`

| 字段 | 说明 |
|---|---|
| `city` | 城市中文名，**带政区后缀**，如 `常德市`、`岳阳市`、`湘西土家族苗族自治州` |
| `province` | 省份全称，如 `湖南省` |
| `adcode` | 行政区划代码，如 `430700` |
| `poi_total` / `district_count` | POI 总数 / 商圈数 |
| `grades` | `{S,A,B,C}` 各级商圈数量 |
| `food` / `xiaocan` / `malls` / `specialties` / `hotels` | **list 型**维度，元素为 POI 记录 |
| `leisure` / `kids` | **dict 型**维度：`{subcats:[{name,count}], list:[POI]}`。`subcats` 是分类统计，**不是 POI** |
| `overview` | `{admin, district_poi[], ...}` 行政区构成与各区 POI 分布 |
| `credibility` | `{poi_total, rated_ratio, dims{}, warnings}` 数据可信度 |
| `districts` / `assoc` | 商圈明细（含 grade/total/poi/food/leisure/kids/hotel）与商圈关联 POI |
| `queries` / `waves` / `updated` / `external` | 采集查询词、批次、更新时间、外部链接 |
| `page` | 站内城市档案页相对路径 |

#### POI 记录

| 字段 | 说明 |
|---|---|
| `mark` | 商圈携带标记，如 `✅A-` |
| `name` | POI 名称 |
| `sub` | 细分 / 备注 / 载体类型 |
| `type` | 高德多段类型串，`;` 分隔，**首段为主类**，如 `餐饮服务;中餐厅;湖南菜(湘菜)` |
| `rating` / `avg` | 评分 / 人均（采集快照，非实时） |
| `addr` / `img` | 地址 / 图片 |

### B2b. 七个维度的真实形态与清洗口径（v0.1.2 全量实测 389 城）

| 维度 | 形态 | 有数据城 | 原始 POI | 清洗后 | 剔除原因 |
|---|---|---:|---:|---:|---|
| `food` | list | 389 | 31021 | 30244 | 777 条 type 首段非餐饮 |
| `xiaocan` | list | 389 | 11816 | 9792 | 2024 条 `sub` 标「仅登记不推荐」/ 重复 |
| `leisure` | dict | 388 | 23080 | 23080 | — |
| `kids` | dict | 382 | 10895 | 10895 | — |
| `malls` | list | 386 | 15892 | 15891 | 1 条重复 |
| `specialties` | list | 386 | 14418 | 14418 | — |
| `hotels` | list | 389 | 12097 | 11835 | 262 条 type 首段非住宿 |
| **合计** | | | **119219** | **116155** | 剔除 3064 |

> **统计口径**：dict 型维度只计 `list` 键下的 POI，`subcats` 的分类条目不计入。早前把 `subcats` 一并遍历会虚增约 4992 条（`leisure` 报成 28072、`kids` 报成 12529），已在 T10 首次实跑中抓到并修正。
>
> **type 字段可用性**：`xiaocan` / `kids` / `malls` 的 `type` 全为空字符串，`leisure` 约 17.8% 为空——这些维度**不能按 type 过滤**，只能按 `sub` 否决标记与去重处理。只有 `food` / `hotels` / `specialties` / `food_top` 的 type 可靠。

### B3. 直辖市结构

`上海市(310100) / 北京市(110100) / 天津市(120100) / 重庆市(500100)` 在 fun 库中各**只有一条**城市档案。moto 的重庆数据按 **25 个城市名**拆分（实测 `routes[].city` 去重：24 个区县名 + 「重庆」本体；早期文档按 `cities[]` 统计为 22，两者口径不同），无对应单城档案，需降级到「重庆市」。各直辖市 `overview.district_poi[]` 有 15 个区级 POI 分布可辅助说明，但没有独立商圈档案，降级仍属精度损失。

### B4. 顶层辅助数据集字段

| 数据集 | 条数 | 关键字段 |
|---|---:|---|
| `provinces[]` | 32 | `province, cities, poi, districts, grades{S,A,B,C}, page` |
| `food_top[]` | 800 | `name, type, rating, avg, address, mark, city, province, city_page, image`；**实测 15 条首段非餐饮**，需按 `is_food()` 清洗后 785 条 |
| `districts_top[]` | 703 | `name, grade(S:180/A:523), shape, rating, poi, total, food, leisure, kids, hotel, city, province, city_page`；按 `total` 四维总分降序 |

### B5. moto 轨迹字段（`routes[].p / w / c`）

实测 1713 条路线 **100% 具备**：`p` 为抽稀 polyline `[lat,lng][]`（GCJ-02，单条最多 3634 点）、`w` 为关键途经点坐标（与 `wn` 一一对应，`w[0]` 恒为集合点）、`c` 为**省份主题色 HEX 字符串**（不是坐标）。默认不输出，需 `--with-track`；体积大，仅地图渲染场景使用。

## C. 两端对齐结论

| 维度 | moto | fun |
|---|---|---|
| 城市名 | 无后缀 `常德` | 带后缀 `常德市` |
| 覆盖 | 31 省 / 360 城 | 32 省 / 389 城 |
| 坐标 | GCJ-02 轨迹 | POI 地址为文字，无坐标字段 |
| 主键 | 路线 `id` | 城市 `adcode` / `city` |

**两端没有共同主键**，只能靠「城市中文名归一化」对齐。这正是 `@references/data-quality.md` 要解决的问题。

## D. 数据源声明

- fun：高德地图 Web 服务 POI（restapi.amap.com）+ 美团 + 大众点评三层数据源。
- moto：市区周边短途来自实地核验数据管线；长途环线为跨市算法聚合条目。
- 两个数据集均为静态快照，不含实时营业状态、排队、票价。
