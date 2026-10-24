# 迭代 4 计划：VLM 计量学注解迁入 feature_catalog（Iteration 4: Metrology Rules Registry）

> **For Claude:** Subagent 优先（1 次重试），失败即主会话手动。禁止 git commit（完成后统一提交）。

**Goal:** 延后清单 #7——把 `call_vlm_critic` 里按对象族硬编码的计量学注解（滚轮/正交管道/轴承座/炮管长度）迁入 `feature_catalog.py` 的规则注册表，新增对象族不再改 agent_loop；迁移保持 VLM prompt 输出**字节级不变**（既有行为零变化），并为这些从未被测过的字符串补上单元测试。

**Architecture:** `feature_catalog.py` 新增 `METROLOGY_RULES` 注册表（每条规则 = detect(feature_metrics) + annotate(feature_metrics, found)，只依赖 feature_metrics 的 cylindrical_faces/bounds_mm）+ `collect_metrology_notes(feature_metrics) -> list[str]`（按注册顺序返回注解块）+ `horizontal_barrel_fragment(feature_metrics)`（炮管长度片段）。`agent_loop.call_vlm_critic` 的 688-779 行内联逻辑替换为注册表调用， Assy 文本拼接顺序保持 wheel→pipe→bearing。

**基线:** 194 tests passed（提交 3ffae89 后干净树）。

### Task 1: 迁移 + 测试
- feature_catalog.py：追加规则注册表（滚动滚轮 ≥2 个 X 轴圆柱 r≥8、正交管道对、Y 轴镗孔 r≥10、水平炮管片段），字符串与现状逐字一致（从 agent_loop.py:704-761 搬运）。
- agent_loop.py：删除内联四段，改为 `collect_metrology_notes` + `horizontal_barrel_fragment` 调用；import 走文件顶部的 feature_catalog 导入区。
- 新建 backend/test_metrology_rules.py：合成 feature_metrics 夹具覆盖 触发/不触发 各规则的断言（含具体数字与关键词），加一个"collect 顺序与拼接"用例。
- 验证：`pytest -q backend/test_metrology_rules.py backend/test_agent_simulation.py backend/test_agent_retrieval_and_contracts.py backend/test_golden_prompts.py` 全绿。

### Task 2: 最终验证 + 提交
全量 pytest + kernel_smoke；`git commit`（feat(vlm): migrate metrology annotations to feature_catalog rules registry）。
