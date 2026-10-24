# 迭代 3 计划：Best-of-N 可视化 + 真投影工程图（Iteration 3）

> **For Claude:** Subagent-Driven：允许 2 并行；被并发限制拒绝（1 次重试）即主会话手动执行。禁止 git commit。

**Goal:** 落地延后清单 #6（Best-of-N 候选评估前端可视化，数据已在 agent_summary.history 产出）与 #4（工程图换成真实投影，替换 /v1/models/{id}/drawing 的假模板）。

**Architecture:** 两任务文件域不相交：T1 只动 index.html；T2 只动 backend/app.py + 新测试。T2 复用 HeadlessCADRenderer（multiview_renderer.py:191，render_stl_multiview(stl_path, output_dir, metrics=...) 返回各视图 PNG 路径）从 artifact 的 model.stl 渲染 TOP/FRONT/RIGHT/ISO 视图，base64 嵌入 SVG 图纸，保留标题栏实测尺寸，结果缓存到 artifact 目录。

**基线:** 190 tests passed（迭代 2 完成态）。

---

### Task 1: Best-of-N 候选评估可视化（index.html）

- `criticCard`（~3012）在 discrepancies 区块后加 `criticCandidates` 容器。
- `updateCriticView`（~5821）：渲染 `round.candidate_evaluations`（字段：candidate/patch_count/patches/status(valid|invalid|budget_exhausted)/rank[5]/metrics/degraded_operations）为候选卡片行：序号、状态徽章、补丁数、体积/包络摘要、rank 前 3 位（valid/feature/dfm）、降级数；status==valid 且 rank 字典序最大者标 ⭐ BEST；patches 用 title tooltip 列 op。空数据隐藏容器。同轮 `round.degraded_operations` 非空时 critic 视图加 ⚠ 徽章。
- CSS 少量 `.critic-candidates`/`.candidate-row` 等沿用 critic 风格。
- 验证：`node --check` 语法门 + grep 绑定。

### Task 2: 真投影工程图（backend/app.py + backend/test_drawing_projection.py）

- `get_model_drawing`：读 manifest 后，若 `model_dir/model.stl` 存在且 `model_dir/drawing.svg` 缓存不存在 → 懒加载 `HeadlessCADRenderer().render_stl_multiview(stl, tmp_views_dir, metrics=metrics)` → 取 TOP/FRONT/RIGHT/ISO 四个 PNG base64 嵌入新 SVG 模板（A3 横版 1000×700：左上 ISO 大图 + 右侧 TOP、左下 FRONT、右下 RIGHT，每图配标签与比例注记，保留原标题栏真实 ENVELOPE/VOLUME/ID/UNITS + html.escape）。写缓存 `drawing.svg` 并返回；渲染器异常 → 记 warning 回退现有模板（端点永不因图纸渲染 500）；缓存存在直接读缓存。
- render_stl_multiview 返回的 dict 键名以实际代码为准（先读 multiview_renderer.py:202-260）。
- 测试 `backend/test_drawing_projection.py`（skipif cq None）：execute_ir 小 IR → cq.exporters 导出 STL 到临时 artifact 目录 + 写 manifest → 调 `get_model_drawing`：断言 SVG 含 `data:image/png;base64`、含真实 ENVELOPE 数字、标题被转义；再调一次断言命中缓存（monkeypatch 渲染计数或比较 mtime 不变）；无 STL 的目录回退旧模板不 500。
- 验证：`pytest -q backend/test_drawing_projection.py backend/test_fallback_guard.py backend/test_quality.py` 全绿。

### Task 3: 最终验证（主会话）

全量 pytest、kernel_smoke、E2E（drawing 端点返回含 base64 视图的 SVG）、`git diff --stat`、总结（不 commit）。
