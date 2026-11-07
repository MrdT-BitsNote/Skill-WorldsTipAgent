# 融合架构说明（v0.2.0）

> 本版把两个单独技能合成**单一技能包**。本文件记录逐文件来源与裁决，供复现与审计。

## 裁决表

| 环节 | 保留/砍削/卸载 | 优先级 | 理由 |
|---|---|---|---|
| 编排大脑 | 保留 travel v0.1.49 全量 | 最高 | 唯一带确定性四灯门禁与 10 章输出契约的一方 |
| 摩旅数据层 | 并入 motofun + 5 夹具 + 数据质量规则 | 高 | 补上 travel 缺的「吃什么/住哪/逛哪」 |
| 双 route.py | travel 保原名，moto 改 `motofun_route.py` | 高 | 同名冲突，总入口与触发词一律不动 |
| 双测试套件 | `tests/` 27 项 + `test/` 202 项适配版 + 一键总入口 | 中 | 包自包含，版本/权限断言按融合口径等价修正 |
| 版本线 | 对外升 0.2.0，正文历史 `v0.2.x` 里程碑标签改 M2/M3 | 中 | 消除版本错位；minor=新能力 |
| 缓存/历史包 | 砍 `__pycache__`、`releases/` 26MB、单独包专用 pack.py | 中 | S7 目录层级硬闸门 + 体积 |

## 文件来源矩阵

| 目标路径 | 来源 | 处置 |
|---|---|---|
| `SKILL.md` | travel v0.1.49 | 改写 frontmatter + 版本线 + 新增融合段/退出门禁；moto 正文不并入 |
| `scripts/*`（49 个） | travel v0.1.49 | 原样 |
| `scripts/motofun.py` | moto v0.1.3 | 原样（保留可选联网，`--offline` 默认走夹具） |
| `scripts/motofun_route.py` | moto `scripts/route.py` | 改名避开冲突；同步改 docstring/prog |
| `references/api-spec.md`、`data-quality.md`、`insights.md` | moto v0.1.3 | 原样，无同名冲突 |
| `fixtures/*.json`（5 个） | moto v0.1.3 | 原样，保持一级目录（S7 标准） |
| `test/run_all.py` | moto v0.1.3 | 适配：ROUTE 路径、版本断言、allowed-tools 等价判据、打包器断言 |
| `tests/run_tests.py`、`tests/test_visa_gate_merged.py` | travel v0.1.49 | 原样 |
| `docs/MOTOFUN_*.md` | moto 的 SKILL/CHANGELOG/QC_REPORT | 卸载归档，避免正文膨胀 |
| `tests/test_fusion.py`、`tests/run_all_fused.py` | 新增 | 融合专项断言 + 一键总入口 |
| `tools/build_fused_pack.py` | 新增 | 固定时间戳打包 + 字节一致校验 |

## 已知冲突与处理

1. **moto T8 断言 `allowed-tools == "Read, Bash"`**：融合版需要 Write/Edit/Glob/Grep，
   改为等价判据「白名单含 Read 与 Bash 且不含 Shell/Exec 类越权工具」——修正适用边界，不放宽。
2. **moto T6 扫全部 `scripts/*.py` 找硬编码密钥**：融合后脚本集扩大到 51 个；
   已实扫 travel 49 个脚本，`password/api_key/` 与动态执行调用 命中均为 0，全包扫描保留。
3. **正文 `v0.2.0` 作历史里程碑标签 7 处**：与对外版本号撞车，统一改 `M2`；`v0.2.1` 改 `M3`。
4. **`__pycache__` 二级目录**：S7 硬闸门会打回，构建时整体剔除；`releases/` 26MB 一并排除。
5. **`audit.py --profile upload` 未安装**：按大厂标准 Step 6 如实标注「上传前自检未执行」，
   降级用包内 `platform_probe.py` 五层 + `tests/test_fusion.py` 的 S7 等价断言覆盖目录层级。

## 不变量（不许在后续版本破坏）

- travel 的触发词、不触发边界、`scripts/route.py` 入口名逐字不动。
- 数据「未核验即灰灯」红线不动，绿灯必须绑定 `source` + `verified_on`。
- 任何数据源失败都不得用编造数据补齐。


## 融合数据层：摩旅路线 × 城市消费（v0.2.0）

> 把「这条路怎么骑」与「骑到这座城吃什么、住哪、逛哪」接成一条链路。
> 数据来自两个公开只读静态集；**默认走 `fixtures/` 离线夹具**，联网只是可选增强。

### 触发条件
用户问到摩旅/跑山/骑行线路、途经城市或「骑完去哪逛」「某城商圈美食」时启用本节；
纯行程编排（天数、预算、交通比选、住宿分房）走 `## 工作流程`，不重复读本节数据。

### 工作流
1. 先跑 `python scripts/route.py "<原话>" --json` 判总意图；若命中摩旅/城市消费，再跑
   `python scripts/motofun_route.py "<原话>" --data-dir fixtures --offline --json`。
2. 取数统一走 `python scripts/motofun.py <city|route|routes|rank|stats> --data-dir fixtures --offline --json`，
   **禁止手拼接口或详情链接**，接口字段口径见 `references/api-spec.md`。
3. 餐饮/酒店/商圈结果必须按 `references/data-quality.md` 清洗：非餐饮 POI 剔除、小吃否决标记、
   维度双形态归一；生效中的不变量见 `references/insights.md`。
4. 摩旅场景先过 `scripts/moto_check.py` 五项门禁（证件·头盔·高速·禁摩·续航），
   再输出消费建议——安全门禁优先于吃喝玩乐。
5. 与行程编排合并时，只把**已确证**的条目写进 §02 交通/§05 餐饮，**不新增章节**。

### 输出契约
- `city` → `{ok, cmd, data:{found, city, food[], hotels[], districts_top[]}}`；
- `route` → `{ok, cmd, data:{intent, commands[]}}`；
- 未覆盖一律 `found=false` + 明确说明"未覆盖"，**不返回空数组冒充查无、不编造 POI**。
- 退出码：`0` 成功 / `1` 输入错误 / `2` 数据源不可用；错误输出为受控 JSON，不裸露 traceback。

### 降级设计（优雅降级与熔断）
- 单一数据源最多重试 **2 次**；仍失败切同级备用源（远端集 → 本地 `fixtures/`）。
- 全部受阻 → 在小册子写一行「该数据获取受限：原因」，基于已确证信息给条件推演；
  **禁止用编造数据补齐缺口**。
- 无联网能力时 `--offline --data-dir fixtures` 照常可跑，并在输出标注"未做实时公开核验"。

### 信源层级与冲突裁决（专业信源矩阵）
- **信源层级要求**：一手官方/原始静态集 > 官方渠道核验结论 > 攻略平台转述；
  每个 volatile 事实带 `source` + `verified_on` + `confidence` 三元组。
- **不可采信类型**：无原始数据支撑的转述、无日期的"网友说"、批量爬取的未核验聚合。
- **冲突三角显式格式**：两源打架时禁止静默选边，正文写
  `> 冲突：A=取值 / B=取值；口径=…；采信=A，理由=…；无法证伪标「待实证」`。
  先统一口径（含税/不含税、构建日期/核验日期），再比层级，最后比时效与利益。

### 自检
- [ ] 是否走了 `route.py` → `motofun_route.py` 两级路由，而非手拼接口？
- [ ] 清洗规则是否按 `references/data-quality.md` 执行，非餐饮 POI 已剔除？
- [ ] 未覆盖是否如实标 `found=false`，没有编造补齐？

