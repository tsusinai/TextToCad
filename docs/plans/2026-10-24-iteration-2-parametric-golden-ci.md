# 迭代 2 计划：参数化闭环 + 回归防护网（Iteration 2: Parametric Loop + Regression Net）

> **For Claude:** 使用 Subagent-Driven Development 执行：任务串行（本环境 subagent 并发上限 1），每任务先尝试派发子代理（1 次重试），失败即主会话手动执行。禁止 git commit。

**Goal:** 落地上轮延后清单中性价比最高的四项——golden 回归集与 CI 完整矩阵（所有后续重构的防护网）、degraded_operations 门禁消费、参数化即时再编译面板、阶段遥测聚合。

**Architecture:** T1 先建防护网；T2 改 agent_loop（门禁消费降级记录）；T3 给 `/v1/ir/compile` 加 `persist` 选项并做前端参数面板（复用现有 GLB 下载/视口链路）；T4 聚合既有 recorder 事件为 manifest telemetry + /health 累计计数。T3/T4 均涉及 app.py，串行执行避免冲突。

**Tech Stack:** 同迭代 1（venv Python 3.11、pytest、无 npm 前端单文件）。CI 容器内补装 `pytest pillow matplotlib`。

**基线:** 167 tests passed（迭代 1 完成态），kernel_smoke PASS。

---

### Task 1: golden prompt 回归集 + CI 完整测试矩阵

**Files:**
- Create: `backend/test_golden_prompts.py`
- Modify: `.github/workflows/quality.yml`

**内容:**
1. golden 集（`@pytest.mark.skipif(app.cq is None)`）：
   - 确定性规划器路径 10 条：a 20mm cube / sphere / cylinder / cone / torus / hexagon prism / hollow cylinder（带孔）/ 中文"一个五边形棱柱" / "two blocks"（复数回归）/ L-bracket 式带孔盒。每条断言：`planner == "deterministic_primitive"`、execute_ir 单实体、bbox 三轴 = 期望值 ±0.05、volume 期望 ±1%、face_count 精确或 ±2。
   - 手工 IR 编译路径 3 条（不走规划器，直接 validate→execute）：法兰（盒+4 孔阵列 cut）、圆角盒（fillet 成功路径无 degraded）、多边形棱柱。断言 metrics + trace 无 `degraded_operations`。
2. CI：`kernel-smoke` job 增加一步 `docker run --rm texttocad-backend:kernel-smoke sh -c "pip install --quiet pytest pillow matplotlib && python -m pytest -q /app/test_*.py"`（Dockerfile `COPY *.py ./` 已含测试文件；timeout 保持 20min）。

**验证:** 本地 `pytest -q backend/test_golden_prompts.py` 全绿；`python -c` 校验 quality.yml 仍是合法 YAML（用 venv 内 pyyaml 或 ruby -e 随手可用项；无则目测+缩进检查）。

---

### Task 2: degraded_operations 接入 MultiGate 门禁

**Files:**
- Modify: `backend/agent_loop.py`
- Modify: `backend/test_agent_simulation.py`

**内容:**
1. 读取 `MultiGateInspector`（agent_loop.py:867 起）现有 gate 结构后：新增"degraded gate"——每轮 `execute_ir(current_ir)`（约 1163/1176 行）与 Best-of-N 候选执行（约 1068 行）后，从 `execution["trace"]` 收集 `degraded_operations`；非空时：
   - round_record 增加 `degraded_operations` 摘要（op+reason 列表）；
   - 作为 warning 级 gate 检查项进 inspector（不直接 fail，除非既有 gate 语义支持 warning）；
   - 注入下一轮 VLM critique prompt 一行提示（"geometry contains degraded ops X, consider re-parameterizing"），让修复循环能针对它行动。
2. 测试：构造含必然失败 fillet 的 IR 跑一轮（mock VLM），断言 round record 含 degraded 摘要且 gate/summary 可见；正常 IR 无该字段。

**验证:** `pytest -q backend/test_agent_simulation.py backend/test_agent_retrieval_and_contracts.py backend/test_multigate_inspector.py` 全绿。

---

### Task 3: 参数化即时再编译面板

**Files:**
- Modify: `backend/app.py`（IRCompileRequest + compile_ir_endpoint）
- Modify: `index.html`
- Create: `backend/test_ir_compile_persist.py`

**后端:** `IRCompileRequest` 加 `persist: bool = False`。persist 时：复用 `_export_face_mapped_glb(shape, glb_path)` 写 `ARTIFACT_ROOT/<new model_id>/model.glb`，写最小 `manifest.json`（model_id/units/geometry_metrics，使 `/v1/models/{id}/download` 与 `/measure` 可用），响应在既有键之上增加 `"model_id"`、`"artifacts": {"glb": "/v1/models/<id>/download?format=glb"}`。失败不落盘。注意 GLB 导出可能返回 None（无 face 映射时）——回退用 trimesh 直转或直接 422 报"persist unsupported for this shape"，取实现简单者并测试覆盖。

**前端:** 新增 "IR PARAMETERS" 折叠面板（复用既有 panel/modal 风格）：
- 数据源 `backendArtifact.design_ir.parameters`，仅渲染数值型 `role=="dimension"` 参数为滑杆+数值框（min=0.1×原值, max=3×原值, step 按量级），非数值跳过。
- 变更后 600ms debounce → 深拷贝 design_ir 更新 parameters[name].value → `POST /v1/ir/compile {ir, persist:true}` → 成功：更新 `currentModelId`、`backendArtifact.glb`、`loadThreePreview()` 刷新视口、面板顶部显示新 bbox/volume/表面积；失败：toast + 恢复原值。
- 无 design_ir / 非 IR 生成时面板禁用并提示。剖切/渲染模式状态在刷新后保持（模型重载后调用 applyRenderMode/refreshSectionClipping 既有函数）。

**测试:** persist 落盘断言（目录/model.glb magic bytes/manifest 可被 measure 读）、非 persist 不落盘、persist 响应含 artifacts 路径且可 GET 200。

**验证:** `pytest -q backend/test_ir_compile_persist.py backend/test_fallback_guard.py`；前端 `node --check` 语法门 + 绑定 grep。

---

### Task 4: 阶段遥测聚合

**Files:**
- Modify: `backend/app.py`
- Create: `backend/test_telemetry.py`

**内容:**
1. 新增 `_summarize_telemetry(recorder, *, llm_calls, vlm_calls)` → `{total_ms, stages: {stage: sum(duration_ms)}, llm_calls, vlm_calls}`（stages 由 events 按 stage 聚合 duration_ms；derived 计数：llm_calls=llm_used?1:0 + agent 轮内 LLM 补丁调用数可从 agent_summary 统计则统计，否则注明 derived）。
2. manifest 写入 `"telemetry"`；模块级 `threading.Lock` 保护的累计计数器 `_TELEMETRY_TOTALS = {"generations": 0, "agent_generations": 0, "failures": 0, "llm_calls": 0, "vlm_calls": 0}`，生成成功/失败处自增；`/health` 返回 `telemetry_totals`。
3. 测试：`_summarize_telemetry` 单元测试（构造 recorder 事件断言聚合）、计数器自增函数单元测试、`/health` 含 telemetry_totals 键。

**验证:** `pytest -q backend/test_telemetry.py backend/test_quality.py`。

---

### Task 5: 最终验证（主会话）

全量 `pytest -q backend/`、kernel_smoke、E2E（8790：cube 生成、compile persist 链路、/health telemetry_totals）、`git diff --stat`、总结（不 commit）。
