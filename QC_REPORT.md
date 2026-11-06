# QC 报告 · v0.2.1 融合版（逻辑修正）

> 本文件中所有数字由 `verify_fused.py` 实跑后写入，未实跑项一律标「未实测」。
> 版本：v0.2.1 ｜ 构建日期：2026-11-05 ｜ 纯标准库断言，不派 agent 跑模型 API。

## 验证集实跑结果

<!--QC_TABLE-->

## DoD 逐项核对

<!--DOD_TABLE-->

## 5 大铁律自评

<!--IRON_TABLE-->

## 已知限制

- `skill-quality-audit/audit.py --profile upload` **未执行**：本机未安装该质检器；
  按大厂标准 Step 6 如实标注，降级用 `platform_probe.py` 五层 + `tests/test_fusion.py` 的 S7 等价断言。
- 质检器 G 判据不在本环境，未实测。
- 融合版未做千问平台净化变体（v0.2.0 保留品牌域名与可选联网脚本）；如需千问包须另做专用变体。
- 不承诺过审 / 上架；平台审核结论以平台通知为准。
