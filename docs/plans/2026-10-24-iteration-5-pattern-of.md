# 迭代 5 计划：负特征 pattern_of（Cutter 阵列）

> **For Claude:** Subagent 优先（1 次重试）→ 手动。完成即独立提交。

**Goal:** 延后清单 #9——让 linear_pattern/polar_pattern 能阵列**切削特征**（`parameters.pattern_of` 指向 cutter 节点），把 N 个实例从宿主中逐一减去；LLM 不再为孔阵列手写 N 个 cut 节点。union 语义（无 pattern_of）零变化。

**设计:**
- 执行器：`_raw_node_shape` 增加 `shapes` 形参（`_node_shape` 已持有，直接透传）；pattern 分支检测 `parameters.pattern_of` → 取 `shapes[target]`（未执行/不存在 → IRExecutionError），生成 count 个实例（linear=translate(i×spacing)、polar=rotate(i×angle/count)，**含 index 0 原位**，因宿主未含 cutter），逐个 `host.cut(instance)`。
- 缓存正确性（镜像 mount target 方案）：cache key 增加 `pattern_target_hash = node_hashes[pattern_of]`，取不到 → 该节点不缓存（宁慢勿错）。
- 校验器：pattern 节点的 `pattern_of` 引用必须存在于 known_nodes，否则 `missing_reference`。
- agent_loop VLM 补丁指南加一行 pattern_of 用法（add_hole_pattern 宏保持不变，向后兼容）。
- 测试 backend/test_pattern_of.py（内核）：polar 4 孔法兰 == golden 值 26263.71；linear 4 孔 == 手工 4-cut 构造等体积；校验器悬空引用拒绝；执行器未知引用 IRExecutionError；同 pattern 节点不同 cutter 半径两次执行体积不同（缓存 key 含 cutter 几何）；无 pattern_of 的 union 语义回归（golden/既有测试覆盖）。

**验证:** `pytest -q backend/test_pattern_of.py backend/test_node_cache.py backend/test_golden_prompts.py backend/test_agent_retrieval_and_contracts.py` 全绿 → 全量 + kernel_smoke → 提交。
