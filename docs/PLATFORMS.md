# 四平台发布包差异台账

四个包**不是同一份文件**。这份文档是唯一登记处：哪个包少了什么、为什么少、少了以后
哪条能力会降级、以及怎么复核。历史上这些差异从没写过，结果是使用者拿到某个包、发现
文档提到的脚本不在包里，只能猜；维护者也不知道自己改的东西进了哪几个包。

**为什么要裁**（不是随便瘦身）：

| 平台 | 硬约束 | 直接后果 |
|---|---|---|
| WorkBuddy | 解压后 ≤ 3 MiB；`SKILL.md` 里点名的文件必须真在包里 | 大脚本与开发文档必须裁，裁了还要改写正文口径 |
| 千问 | 零 http(s) 外链（机检）；定位国内旅行，出境数据与绿网高风险面不收 | 出境整条链路与含域名文案的脚本一律不进包 |
| SkillHub / DuMate | 无体积与外链硬约束 | 作为**全量基准**，其余三包与它对比 |

## 一、实测差异表

<!-- PLATFORMS:BEGIN 由 tools/platform_diff.py --write 生成，勿手改 -->

> 版本 **v0.2.276** ｜ 本表由 `tools/platform_diff.py --write` 实测生成，由 `--check` 在自检中复算。

| 平台 | 脚本 | 文档 | 文件数 | 解压后 | zip | 相对全量包的裁剪 |
|---|---|---|---|---|---|---|
| SkillHub（全量基准） | 40 | 19 | 132 | 4.25 MiB | 1.53 MiB | —（基准） |
| 百度 DuMate | 40 | 19 | 132 | 4.25 MiB | 1.53 MiB | 无 |
| WorkBuddy | 34 | 12 | 95 | 2.91 MiB | 0.98 MiB | 缺脚本 6：compute_plugin.py、credibility.py、motofun.py、motofun_route.py、render_booklet.py、site_query.py；缺文档 7 |
| 千问（零外链 / 国内定位） | 32 | 11 | 85 | 2.79 MiB | 0.93 MiB | 缺脚本 8：compute_plugin.py、credibility.py、gate_card.py、motofun.py、motofun_route.py、outbound_safety.py、render_booklet.py、site_query.py；缺文档 8 |

- **WorkBuddy 缺的文档**：CHANGELOG.md、FAQ.md、MOTOFUN_CHANGELOG.md、MOTOFUN_QC_REPORT.md、MOTOFUN_UPSTREAM_SKILL.md、PLATFORMS.md、SHOWCASE.md
- **千问（零外链 / 国内定位） 缺的文档**：CHANGELOG.md、FAQ.md、MOTOFUN_CHANGELOG.md、MOTOFUN_QC_REPORT.md、MOTOFUN_UPSTREAM_SKILL.md、OUTBOUND.md、PLATFORMS.md、SHOWCASE.md

体积列随文档改动浮动，不参与强校验；脚本/文档清单与文件数参与。

<!-- PLATFORMS-SIG
skillhub|scripts=40|docs=19|files=132|miss_scripts=|miss_docs=
dumate|scripts=40|docs=19|files=132|miss_scripts=|miss_docs=
workbuddy|scripts=34|docs=12|files=95|miss_scripts=compute_plugin.py,credibility.py,motofun.py,motofun_route.py,render_booklet.py,site_query.py|miss_docs=CHANGELOG.md,FAQ.md,MOTOFUN_CHANGELOG.md,MOTOFUN_QC_REPORT.md,MOTOFUN_UPSTREAM_SKILL.md,PLATFORMS.md,SHOWCASE.md
qianwen|scripts=32|docs=11|files=85|miss_scripts=compute_plugin.py,credibility.py,gate_card.py,motofun.py,motofun_route.py,outbound_safety.py,render_booklet.py,site_query.py|miss_docs=CHANGELOG.md,FAQ.md,MOTOFUN_CHANGELOG.md,MOTOFUN_QC_REPORT.md,MOTOFUN_UPSTREAM_SKILL.md,OUTBOUND.md,PLATFORMS.md,SHOWCASE.md
-->
<!-- PLATFORMS:END -->

## 二、裁掉的东西，能力上等于什么（诚实口径）

按**影响的能力**登记，不按文件登记 —— 使用者关心的是「这个包里我还能做什么」。

| 被裁对象 | 不在哪些包 | 能力影响 | 包内替代口径 |
|---|---|---|---|
| 九风格增强渲染器（`render_booklet.py`） | WorkBuddy、千问 | `--rich` 拿不到九风格册子 | `--rich` **自动降级**为紧凑卡册：stderr 打 `[DEGRADED]`、manifest/JSON 带 `degraded=true` 与 `degrade_reason`，不再产出 0 字节后静默失败 |
| 可信度内核（`credibility.py`） | WorkBuddy、千问 | volatile 事实没有脚本化「未核验」角标 | 按 `references/stability.json` 三档**人工判读**；正文明确禁止自称「已核验」 |
| 实算插件（`compute_plugin.py`） | WorkBuddy、千问 | 城际里程/驾车时长不做地图实算 | 用内置数据里的里程与经验值，标注「按画像经验值估算」 |
| 签证/准入门禁卡（`gate_card.py`） | 千问 | 没有红黄绿灰四灯门禁卡 | 千问档整体不做出境，门禁卡无输入，故不适用 |
| 出境安全编排（`outbound_safety.py`） | 千问 | 无出境安全编排 | 千问档定位国内旅行 |
| 联网采集（`motofun.py` / `motofun_route.py` / `site_query.py`） | WorkBuddy、千问 | 不能联网拉自有站点数据 | 只用包内离线数据；文档已改成「不联网、不拼接外部接口」 |
| 开发/过程文档（变更记录、质检报告、DoD、安装说明、融合对照…） | 各包按需 | 无功能影响 | `README.md` + `SKILL.md` 覆盖使用者所需 |

## 三、复核方式

```bash
# 生成 / 更新上面的差异表（以 dist/ 里的实测包为准，不凭构建器常量推断）
python tools/platform_diff.py --write

# 校验文档与实测包一致（不一致 → 退出码 1）
python tools/platform_diff.py --check

# 源码 + 四包整体自检，其中包含「跨平台差异表与实测包一致」这一判据
python tools/selfcheck.py --pack dist/…-workbuddy.zip --pack dist/…-skillhub.zip \
    --pack dist/…-dumate.zip --pack dist/…-qianwen.zip
```

差异表是**生成物**：手改会在下一次 `--check` 时被判为漂移。要改差异，先改构建器的
裁剪清单，再重建包，最后 `--write`。
