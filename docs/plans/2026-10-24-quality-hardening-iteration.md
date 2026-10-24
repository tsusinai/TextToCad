# 质量加固迭代计划（Quality Hardening Iteration）

> **For Claude:** 使用 Subagent-Driven Development 执行本计划：每个任务派发全新 subagent，任务完成后审查；同批次最多 3 个并行，且同一批任务的**文件域互不相交**（见每任务的 Files 清单，越界即违规）。

**Goal:** 修复三路并行代理（代码审查 / 前瞻探索 / 全流程测试，2026-10-24）发现的 1 Critical + 4 Important 缺陷与 fallback 守卫漏洞，落地 agent 延迟预算，使当前未提交变更达到可安全提交状态。

**Architecture:** 两批执行。Batch A（T1 几何缓存+执行器 / T2 agent 循环 / T3 前端单文件）三任务并行，文件域分别为 `ir_executor.py`、`agent_loop.py`、`index.html`；Batch B（T4 app.py 守卫 / T5 schema 0.3 收口）两任务并行，文件域分别为 `app.py`、`ir_validate.py+ir_schema.py+test_quality.py`。全部完成后跑最终全量验证。

**Tech Stack:** Python 3.11（必须用 `backend/.venv/Scripts/python.exe` / `pytest.exe`，系统 Python 3.12+ 与 CadQuery/numpy<2 不兼容）、FastAPI、CadQuery 2.4.0/OCCT、pytest；前端为无构建纯静态 Three.js 单文件（禁止引入 npm/Node 依赖）。

**基线状态:** 122 个自动化测试全部 PASS，kernel_smoke PASS，端到端 fallback 生成链路绿，前后端契约一致。工作树含既有未提交变更——**所有任务禁止 `git commit`**，提交由用户在最终验证后统一决定。

---

## 全局约束（每个 subagent 必须遵守）

1. 工作目录 `D:\AIProject\TextTo3D`；测试一律用 venv 解释器。
2. 只允许修改本任务 Files 清单内的文件；测试新增文件用任务指定的新文件名，避免同批冲突。
3. 禁止 git commit / push；禁止新建 package.json / npm 依赖。
4. 代码风格与周边一致；注释只写代码本身表达不了的约束。
5. 完成标准 = 任务内验证命令全绿 + 报告（改动 file:line 清单、新增测试与结果、与计划的偏差）。

---

### Task 1: 形状缓存正确性修复 + 降级操作可见性

**Files:**
- Modify: `backend/ir_executor.py`
- Create: `backend/test_node_cache.py`（新测试文件，同批无他人使用）

**问题（代码审查 C1 + 机会#5，证据行号为当前工作树）:**
1. **C1（Critical）** `_NODE_SHAPE_CACHE`（ir_executor.py:1027-1068）缓存 key 不完整：遗漏 (a) mount target 的几何内容（`_apply_mount` 按 `shapes[target_id]` 包围盒定位，而 target 可以不在 `inputs` 里）；(b) 节点级 `frame`/`rotation`/`orientation`（`_raw_node_shape` 708/712-713 行会读取）；(c) 节点 `id` 语义（id 决定 cylinder/extrusion 1.5mm 重叠与 cutter 对中镗孔行为，572-575/611 行）。跨请求/跨 Best-of-N 候选会返回**摆放错误或行为错误的几何**。
2. **机会#5** fillet/chamfer/shell 失败时静默降级（ir_executor.py:955-957、985-988 `except → warning + return inputs[0]`），质量门完全看不到。

**修复方案:**
1. 缓存 key 扩充：`node_hash_data` 纳入节点全部顶层字段（含 `id`、`frame`、`rotation`、`orientation`，即整个 node dict 的稳定序列化），并加入 `"mount_target_hash": node_hashes.get(str(mount_data.get("target")))`（target 几何变化 → key 变化）。若实现中发现无法稳定取得 target hash（target 未执行过），则该节点**跳过缓存**（宁慢勿错）。顺带：命中时移到尾部（FIFO→LRU）；`if ref in node_hashes` 解析失败静默丢 key 的路径改为显式跳过缓存。
2. 新增降级可见性：fillet/chamfer/shell/pattern 等 `except Exception` 降级处，向该节点的 trace/execution 记录追加 `degraded_operations: [{op, reason}]`（跟随现有 trace 结构，看 `execute_ir` 返回值怎么组装 trace，保持一致），供上层（MultiGate/agent 循环）消费。本任务只做**记录**，不改门禁判定（warning 级）。

**测试（先写失败测试再实现）:**
- `test_cache_miss_when_mount_target_geometry_changes`：同规格 turret 两次执行，mount target（hull）尺寸不同 → 两次输出的 bbox 不同（旧行为：命中脏缓存返回相同摆放）。构造参考 `backend/test_assembly_repair.py` 的 tank 夹具写法。
- `test_cache_miss_when_node_rotation_differs`：同 parameters、不同 `rotation` 的两节点 bbox 不同。
- `test_cache_hit_when_identical_ir`：完全相同 IR 两次执行 → 第二次命中缓存（用计数器或 monkeypatch `_raw_node_shape` 调用次数断言只执行一次）。
- `test_degraded_fillet_recorded`：构造必然失败的 fillet（如对无该面的 box 引用不存在的 edge/超大半径），断言 trace 里出现 `degraded_operations` 且几何仍返回（不抛）。

**验证命令:**
```
backend/.venv/Scripts/pytest.exe -q backend/test_node_cache.py
backend/.venv/Scripts/pytest.exe -q backend/test_assembly_repair.py backend/test_canonical_scale_and_assembly.py
```
预期：新测试全 PASS，既有装配套件不回归。

---

### Task 2: agent 循环错误路径 + 候选排序 + 延迟预算

**Files:**
- Modify: `backend/agent_loop.py`
- Modify: `backend/test_agent_simulation.py`（同批无他人使用）

**问题:**
1. **I1（Important）** 回滚失败路径（agent_loop.py:1125-1131）置 `primary_shape=None` 后继续跑，1161 行 `renderer.render_stl_multiview(temp_stl,...)` 无条件执行 → `FileNotFoundError`（multiview_renderer.py:64）掩盖真实 `IRExecutionError`。最常见触发：首轮 IR 即非法（`last_valid_ir == initial_ir`，回滚必然同样失败）。
2. **候选排序 tie-break 符号疑似反了**（agent_loop.py:1050）：由 `-len(nodes)` 改为 `len(variant)`（正号），同分时**补丁更多**的候选胜出。结合本项目"保护已验证基本体、最小修复优先"的哲学（见 `_select_patch_candidate` 上下文与 git log 37439d2），应恢复最小补丁优先。
3. **机会#2（高影响）** agent 模式最坏路径（4 轮 × VLM 35s 超时 + 4 视图渲染 + 6 候选串行内核执行）> 90s，而前端 index.html:6116 硬超时 90s 会 `abort()+DELETE` 任务——第 3 轮收敛前就被杀。注意：前端文件归 Task 3，本任务**只改服务端**。

**修复方案:**
1. 回滚再失败时：记 warning 后 **`raise` 原始 `exec_err`**（不再带着 None 往下走到渲染）；若 `exec_err` 之外还有修复轮次可用则可 `break` 进入修复轮（二选一，取实现更简单且测试可覆盖者，报告里说明选择）。
2. tie-break 恢复负号（最小补丁优先），加注释说明意图。
3. 延迟预算：`run_agent_loop`（或入口函数）开头 `deadline = time.monotonic() + float(os.getenv("AGENT_TIME_BUDGET_SECONDS", "80") or 80)`；每轮修复循环顶部与 Best-of-N 候选循环内检查 `time.monotonic() > deadline` → 提前退出并采用当前 Best-of-N 最优（保持返回结构不变，在 summary/history 里记录 `budget_exhausted: true` 与已完成轮数）。VLM/LLM 单次调用超时保持 35s 不动。

**测试:**
- `test_rollback_failure_raises_original_error`：monkeypatch 使初始 IR 执行失败且修复不可用（或首轮即非法），断言抛出的是原始 `IRExecutionError`（消息含真实原因），而非 FileNotFoundError。
- `test_tie_break_prefers_fewer_patches`：构造两个同分候选（一多补丁一少补丁），断言选出少补丁者。
- `test_time_budget_exits_early_with_best_candidate`：monkeypatch `time.monotonic` 推进或设 `AGENT_TIME_BUDGET_SECONDS=0`，断言循环立即退出、返回当前最优候选且 `budget_exhausted` 标记为真。
- 既有 `test_agent_simulation.py` 全部不回归。

**验证命令:**
```
backend/.venv/Scripts/pytest.exe -q backend/test_agent_simulation.py backend/test_agent_retrieval_and_contracts.py
```

---

### Task 3: 前端收尾——渲染节流回归、死 UI 接线、小加固

**Files:**
- Modify: `index.html`
- Modify: `.gitignore`（追加一行 `gui-audit-screenshots/`）

**问题:**
1. **I3（Important）** on-demand 渲染循环（index.html:4063-4098，连续 4 帧空闲即停）漏触发：`setGridVisible`（4235-4243）改 `grid.visible` 后、`applyPreviewMaterial`（4373，调用点 6320-6326）换材质后都**不调用 `requestThreeRender()`** → 循环停后画面冻结。
2. **I2（Important）** 约 500 行"死 UI"零 JS 绑定：剖切工具栏（2805-2825：轴按钮/深度滑块/`sectionFlipBtn`）、量测 HUD（2826-2846：`viewportMeasureHud`/`measureBbox`）、工具栏入口（2759-2761：`toggleMeasureHud`/`toggleSectionBar`/`renderModeSelect`）、蓝图弹窗（3028-3045：`drawingModal`/`btnDownloadSvg`/`btnPrintDrawing`/`closeDrawingModal`）。后端端点已存在：`GET /v1/models/{id}/measure`（app.py:4513）、`GET /v1/models/{id}/drawing`（app.py:4432，返回 SVG）。点击全部无效。
3. **Minor** toast `el.innerHTML` 直接插值（6501-6503，改 textContent 组装或转义）；`window.open(...,'_blank')`（6443）加 `'noopener,noreferrer'`。

**修复方案:**
1. 两处补 `requestThreeRender()`，并 grep 全文件所有直接改 scene/材质/grid 状态的路径逐一确认都有重绘触发（报告列出核对清单）。
2. 死 UI 接线（复用页面既有 fetch/状态模式，读附近代码照抄风格）：
   - `toggleSectionBar` 开关剖切栏；轴按钮 X/Y/Z 设置 `THREE.Plane` clipping（renderer 需 `localClippingEnabled=true`），深度滑块调 constant，`sectionFlipBtn` 翻法向；关闭时清 clipping 恢复完整显示。
   - `renderModeSelect`：Shaded（默认材质）/ X-Ray（透明度+depthWrite=false 线感）/ Wireframe（`wireframe=true`）三态切换当前 GLB 材质，切换后触发重绘。
   - `toggleMeasureHud`：取当前 `modelId` 调 `/v1/models/{modelId}/measure`（带与其它 fetch 一致的 headers/错误 toast），把 bbox/尺寸填进 `measureBbox` 等 HUD 字段；无模型时禁用。
   - 蓝图弹窗：工具入口改为打开 `drawingModal` 并把 `/v1/models/{id}/drawing` 的 SVG 填入预览区（`<img src=...>` 或 fetch 后注入，注入须 textContent/受控方式，防 XSS）；`btnDownloadSvg` 触发下载 blob；`btnPrintDrawing` 用隐藏 iframe 打印；`closeDrawingModal` 关闭。既有 `exportDrawing` 的 `window.open` 路径保留但加 noopener。
   - 所有按钮加 `disabled`/空态处理，不得出现 undefined 引用崩溃。
3. 语法门：若本机有 `node`（`node --version` 可用），把内联 `<script type="module">` 抽到 temp `.mjs` 后 `node --check` 通过；无 node 则静态自查每个新增函数的括号/引号配对并报告。

**验证命令:**
```
grep -c "requestThreeRender" index.html   # 应比改动前增加
grep -n "toggleSectionBar\|toggleMeasureHud\|renderModeSelect\|closeDrawingModal" index.html  # 每个 id 应同时出现在 HTML 与 JS 绑定
```
人工验收点（写进报告）：剖切开/关/翻面、三渲染模式、量测 HUD 拉取真实数据、蓝图弹窗预览+下载。

---

### Task 4: app.py 守卫与清理——fallback 词边界、死代码、冗余计算

**Files:**
- Modify: `backend/app.py`
- Create: `backend/test_fallback_guard.py`（新测试文件）

**问题:**
1. **测试缺陷 4f（必修）** 确定性规划器 primitive 词表裸子串匹配（app.py:1580-1588）：`"gon" in "an ergonomic desk organizer for pens"` 为 True → 无 LLM 时自由文本**绕过 503 守卫**，静默生成 120×80×42 错误方块。同类风险 token：`ring`（bring/string）、`ball`（balloon）、`cone`、`block`（blockade）。
2. **I5** `measure_model` 末尾整段不可达死代码（app.py:4539-4553，首个 return 之后的重复 return 块）。
3. **Minor** `app.py:3231-3232` 对同一 shape 调两次 `_shape_metrics`（Volume/Area/BRepCheck_Analyzer 都很贵）且 manifest 双份冗余。
4. **Minor** `app.py:4455-4458、4517-4523` `json.loads(manifest...)` 与 `float(bbox.get(...))` 无容错，manifest 损坏/字段 null → 500。
5. **配合 T5** `_normalize_ir_draft`（app.py:1237-1238）把 0.3 静默改写回 0.2：改为**仅当文档不含 `components`/`instances`/`assembly_joints` 键时**才降写 0.2，含装配结构的 0.3 文档保留原版本号交给校验器（T5 会使其得到明确校验结果）。

**修复方案:**
1. 新增 `token_matches(text, token)`：CJK token（含非 ASCII）保持现有子串匹配；ASCII token 用词边界正则——普通词 `\btoken\b` 全词匹配；**显式后缀型 token（当前仅 `gon`，意图匹配 pentagon/hexagon/octagon 等）用 `\w*gon\b`**。先读 1580-1587 实际词表再定后缀白名单，报告中列出每个 ASCII token 使用的匹配规则。`"gon"` 不得匹配 "ergonomic"/"gone"。
2. 删除 4539-4553；`metrics = _shape_metrics(shape)` 复用；manifest 读取包 try/except 返回 404/422（与端点现有错误风格一致）。

**测试（新文件 `backend/test_fallback_guard.py`，用 FastAPI TestClient，参考 test_quality.py 既有 mock 手法，无需 LLM）:**
- `test_freeform_text_with_gon_substring_returns_503`：`"an ergonomic desk organizer for pens"` → 503（回归用例，旧行为 200）。
- `test_hexagon_prompt_still_deterministic`：`"a hexagon prism 30mm"` → 200 且 planner=deterministic_primitive。
- `test_ring_in_bring_not_matched`：`"bring me a nice chair"` → 503。
- 中文回归：`"一个五边形棱柱"` → 200 deterministic。
- `test_drawing_endpoint_bad_manifest_returns_4xx`：损坏 manifest → 404/422 而非 500。

**验证命令:**
```
backend/.venv/Scripts/pytest.exe -q backend/test_fallback_guard.py backend/test_quality.py
```

---

### Task 5: schema 0.3 收口——交叉引用校验与显式拒绝

**Files:**
- Modify: `backend/ir_validate.py`
- Modify: `backend/ir_schema.py`（如需错误码/消息常量）
- Modify: `backend/test_quality.py`（更新既有 `test_ir_schema_v0_3_assembly_validation` 并新增用例）

**问题（I4）:** schema 0.3 只做了半个：`validate_ir` 不校验 `instance.component` 是否存在、joint 引用的 instance、component 内 outputs 引用、component/instance id 重复（ir_schema.py:70-106 三个新模型形同虚设）；执行器只读顶层 `nodes`，components-only 的 0.3 文档静默丢弃装配结构或报 "IR has no valid output node"。既有测试 `test_ir_schema_v0_3_assembly_validation`（test_quality.py:984-1016）把半成品契约固化成"合法"。

**修复方案:**
1. `validate_ir` 增加交叉引用校验（错误进现有 errors 列表结构，风格照抄周边）：
   - 每个 `instance.component` 必须能在 `components` 里按 id 找到；
   - 每个 `assembly_joints` 引用的 instance id 必须存在；
   - 每个 component 的 `outputs` 引用的节点 id 必须在该 component 的 `nodes` 内；
   - component id / instance id 各自唯一，且不得与顶层 node id 冲突。
2. 混合文档（0.3 且**同时**有顶层 outputs 与 components）：保持合法（顶层照旧执行，装配结构暂不执行——这是已知限制）；**components-only（无顶层可执行输出）的 0.3 文档 → 明确校验错误**，消息指明 "assembly-only IR v0.3 documents are not executable yet; provide top-level nodes/outputs"。（执行器 `ir_executor.py` 归 Task 1 文件域，本任务**不改执行器**；显式拒绝放在校验层即可达成"不再静默丢弃"。）
3. 更新 test_quality.py：`test_ir_schema_v0_3_assembly_validation` 拆为 合法混合文档 PASS / components-only 拒绝 / 悬空引用拒绝（instance.component 不存在、joint 引用不存在、outputs 悬空、id 重复）等独立用例。

**验证命令:**
```
backend/.venv/Scripts/pytest.exe -q backend/test_quality.py
```

---

### Task 6: 最终验证与整合审查（串行，主会话执行）

1. 全量套件：`backend/.venv/Scripts/pytest.exe -q backend/`（排除需要真实 LLM 的路径，如 CI 一样 mock）。
2. `backend/.venv/Scripts/python.exe backend/kernel_smoke.py`。
3. E2E 复测（空 `LLM_API_KEY` 起 8790 端口）：/health、"a 20mm cube" 生成全链路、`"an ergonomic desk organizer for pens"` 现在应 503、坏输入 422。
4. `git diff --stat` 总览 + 抽查 T1/T2 高风险改动点。
5. 汇总报告给用户（不 commit，由用户决定）。

---

## 延后到下轮迭代（来自前瞻探索报告，本轮不做）

| # | 机会 | 影响/工作量 | 延后理由 |
|---|------|------------|----------|
| 1 | 参数化即时再编译面板（前端滑杆 → `/v1/ir/compile`） | 高/2-4人日 | 独立特性，等本轮地基稳定 |
| 3 | CI 跑完整 pytest 矩阵 + golden prompt 回归集 | 高/2-3人日 | 需 Docker job 改造与 golden 集设计 |
| 4 | 工程图换成真实投影（复用 HeadlessCADRenderer/HLR） | 中高/2-3人日 | 依赖 #3 的回归防护先行 |
| 6 | Best-of-N 候选评估前端可视化 | 中/2人日 | 数据已产出，UI 独立可加 |
| 7 | VLM 计量学注解迁入 feature_catalog | 中/2人日 | 重构型，需 golden 集护航 |
| 8 | 阶段延迟/LLM 成本遥测 | 中/1-2人日 | 跨 app.py+agent_loop.py，避免与本轮冲突 |
| 9 | 负特征 `pattern_of`（cutter 阵列） | 中/3-4人日 | 触及执行器 DAG 语义，需 golden 测试 |
| 10 | 装配间隙检查接入主生成链 | 中/2-3人日 | 可能抬升失败率，先 warning 试运行 |

**明确不做（YAGNI）**：分布式队列/多 worker、完整 2D 草图约束求解器、前端 Vite/React 拆分——理由见探索报告。
