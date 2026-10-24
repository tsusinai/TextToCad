# 迭代 6 计划：装配间隙检查接入主生成链（warning 级）

> **For Claude:** 独立迭代；完成即提交。

**Goal:** 延后清单 #10——多输出装配 IR 在主生成链内做**两两实体间隙/干涉检查**（复用 `_shape_distance`/`_shape_intersection_volume`/`_classify_clearance`），结果以 warning 级写入 `checks["assembly_clearance"]`（进 manifest 与 GenerateResponse），**不进 hard_checks、不使生成失败**。单输出 IR 零影响（不加键）。

**设计:**
- `_assembly_clearance_report(output_shapes, process_profile)`：≥2 个输出实体时两两检查，产出 `{status, checked_pairs, required_clearance_mm, pairs:[{pair, status, distance_mm, intersection_volume_mm3, reason...}], hard: False}`；status 聚合 interference > warning > contact > pass。
- 接线：`_generate_ir_model` checks 构建处（~4143）在 `all_outputs_valid` 后追加，`PROCESS_PROFILES.get(params.process)` 供 profile。
- 测试 backend/test_assembly_clearance.py（内核）：双圆柱相距 30mm → pass 且 distance≈20；错位 6mm → interference 且 intersection>0；单输出 → None；hard=False 契约。

**验证:** 新测试 + 全量 + kernel_smoke → 独立提交。
