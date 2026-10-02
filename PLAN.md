# TextToCad phased product plan

This plan moves TextToCad from a prompt demo to a trustworthy, manufacturable CAD workspace. The first phase is deliberately narrow: a user should understand what the system interpreted, see whether the result passed checks, and recover an earlier revision.

## Phase 1 — Trustworthy generation loop

Status: implementing in this release.

Deliverables:

- Interpretation preview with dimensions, compartments, edge treatment, units, and explicit default assumptions.
- Generation state that distinguishes local preview from a backend OCCT B-Rep result.
- Dynamic manufacturing checks driven by backend validation when available and by conservative local checks offline.
- Local revision history with prompt, interpreted parameters, source, timestamp, restore, and clear actions.
- Graceful backend failure: the preview remains usable and the UI explains that STEP/STL requires a connected backend.

Acceptance criteria:

- A user can inspect the interpreted specification before generating.
- A generated revision can be restored after another prompt is used.
- The readiness panel updates after every generation and does not show stale results.
- A backend response with failed checks is visible as a warning instead of being presented as fully ready.
- The same behavior works in English and Chinese.

## Phase 2 — Conversational parametric editing

Status: completed in this release.

Delivered:

- Follow-up instructions for relative and absolute width, depth, height, wall, chamfer, and compartment edits.
- Canonical prompt generation so edited browser specs can be sent to the geometry backend.
- A feature tree showing the base solid, shell, compartments, and edge treatment.
- Revision diffs showing changed parameters and one-click restoration of an exact canonical revision.
- Three consecutive edits can be made without rewriting the original design prompt.

Acceptance target: a user can make three consecutive edits without rewriting the original prompt.

## Phase 3 — Manufacturing-grade CAD

Status: completed in this release.

Delivered:

- FDM, SLA, CNC, and injection molding process profiles in the frontend and backend.
- Process-aware wall thickness, edge treatment, overhang, draft, clearance, and export checks.
- Wall-map samples and localized issue markers in the manufacturing panel.
- Reproducible STEP/STL manifests containing units, process profile, parameters, checks, analysis, and generator version.
- AP242 STEP export attempt with an explicit fallback schema recorded in the manifest.
- Optional 3MF and GLB preview artifacts with download endpoints.
- Backend endpoint for retrieving process profiles and per-model analysis.

Follow-up work for the next CAD kernel iteration:

- Replace parametric wall samples with face-level thickness maps.
- Add true draft angles, machining access, support-aware orientation, and process-specific feature generation.
- Expand AP242 product metadata and preview materials.

Acceptance target: every exported model includes units, parameters, checks, and a reproducible generation manifest.

## Phase 4 — Collaboration and scale

Add shareable project links, persistent storage, background job queues, signed artifact URLs, rate limits, usage telemetry, and team permissions.

Acceptance target: long-running jobs survive page refreshes and artifacts remain downloadable from a project revision.

## Product guardrails

- Never hide a default assumption; show it beside the interpreted values.
- Never report a manufacturing check as passed unless the current revision was checked.
- Keep geometry deterministic and versioned at the backend boundary.
- Keep Chinese and English flows feature-equivalent.

## Measurement

Track interpretation confirmation rate, valid-B-Rep rate, median generation time, backend failure rate, revision restore rate, export success rate, and manufacturing check failures by process profile.


## Astra 全局优化执行（2026-10-02）

本轮已完成第一批 P0 稳定性与体验改进：

- 后端生成后持久化 \`manifest.json\`，并让 \`export_ready\` 只在 STEP、STL、分析文件及可选预览文件实际写入后变为 true。
- 生成开始时清理超时产物；生成失败会删除当前模型的部分产物，避免磁盘泄漏。
- 对规范化提示词和工艺建立进程内缓存，并用导出锁串行化 STEP schema 设置，减少重复建模和并发导出风险。
- 前后端统一托盘、线缆夹、花盆、灯座、笔筒的类型与标题，连续编辑时保留模型类型。
- 前端生成请求加入 \`AbortController\`、序列号防竞态、异常收敛和明确的本地预览提示。
- 3D 预览支持拖动旋转、Shift+拖动平移、滚轮缩放、双击/ FIT 复位，视图切换会回到可预测的相机状态；交互提示随中英文切换。
- STEP/3MF/GLB 按后端真实返回的能力显示，避免点击后再触发无效生成。

验证标准：主分支和 \`gh-pages\` 的前端脚本通过 \`new Function\` 语法检查；两分支 index 内容一致；后端静态审查确认清单写入、产物清理、类型解析和失败回收路径存在。

## Astra 第二轮体验优化（2026-10-02）

已完成生成取消/超时、阶段状态、名义制造评审、模型类型语义预览、花盆排水孔、灯座走线槽、键盘视图操作、无障碍视图状态和移动端导出换行。真实 GLB 对象视图与面级分析保留为下一阶段。

## 第三轮交互与生成优化（2026-10-02）

已完成异步 job/status/cancel 接口、可编辑参数卡、渐进式 GLB/OrbitControls 视图和 SVG 降级；面级制造采样与持久化队列继续排入下一阶段。

## LLM intent layer（本轮完成）

- 高级模式接入 OpenAI-compatible Chat Completions；标准模式仍为无 API 的确定性解析。
- LLM 只返回受限 JSON 参数，后端进行类型、范围、有限枚举和布尔值校验，再交给 CadQuery/OCCT 建模与 B-Rep 校验。
- 后端记录 mode、llm_used 和 assumptions；API key 只存在后端环境变量，前端不接触密钥。
- provider 缺失、超时、响应过大或 JSON 无效时，安全回退到确定性基线，并在 UI 显示原因。
- 前端保留原始自然语言与基线参数，支持中英文模式切换、后端能力探测和高级特征树展示。

下一轮：增加结构化 JSON Schema 校验、provider 预算与速率限制、可选的二次几何修复建议，以及真实 CadQuery 回归样例集。

## 第四轮后续校验

Astra 审查补充的体验与稳定性工作已落地：真实 GLB 预览生命周期清理、取消旧加载、隐藏时停止渲染、SVG 概念预览提示、LLM provider 兼容回退和取消任务产物清理。上线前仍需用真实生成的 organizer/plant/lamp GLB 样例核对 Z-up 到 Y-up 的三视图方向，并在带 WebGL 的浏览器完成连续生成压力验证。
