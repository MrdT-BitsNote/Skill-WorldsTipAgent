# DoD 清单 · v0.2.0 融合版

| # | 判据（可执行断言） | 验证方式 |
|---|---|---|
| D1 | 两个源技能的触发词在融合版 `description` 中逐字保留，且负向边界存在 | `tests/test_fusion.py` F3 |
| D2 |  visa 未核验一律灰灯，绿灯绑定 `visa_verified` + `visa_source` + `verified_on` | `tests/test_visa_gate_merged.py` |
| D3 | 双路由入口并存、各自可跑且行为不同 | `tests/test_fusion.py` F4 |
| D4 | 断网 `--offline --data-dir fixtures` 能取到真实夹具数据，未覆盖城市如实 `found=false` | `tests/test_fusion.py` F5 |
| D5 | 包内无二级嵌套目录、文件层级 <=2 | `tests/test_fusion.py` F1 + `platform_probe.py` [2] |
| D6 | frontmatter 5 必填齐、版本四处一致 | `tests/test_fusion.py` F2 + `platform_probe.py` [4] |
| D7 | 一键总入口 EXIT 0，四个套件全 PASS | `tests/run_all_fused.py` |
| D8 | zip 内文件与源码字节一致、根含 SKILL.md、固定时间戳 | `tools/build_fused_pack.py --verify` |
| D9 | lint BLOCKER=0 且分数不低于基线 A/100 | `skill_lint.py --target .` |
| D10 | 结论中的分数/编号/退出码全部来自实跑，未实测项明确标注 | 本报告 |
