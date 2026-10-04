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

## Advanced CAD pipeline upgrade（Semantic CAD IR v0.1）

参考更先进 CAD 链路，本轮开始把当前参数 JSON 升级为可追踪的 Semantic CAD IR：

- design：模型族、用户意图、模式、LLM provenance、assumptions。
- parameters：数值、单位、来源和 hard/derived/soft 约束。
- datums：基础 XY/YZ/XZ 参考。
- features：基础实体、壳体、隔板、切除、孔阵列和边缘处理的 Feature DAG 初稿。
- constraints：尺寸范围与工艺壁厚规则。
- builder：固定为 CadQuery/OCCT。

每个 revision 的 manifest 现在保存 design_ir，并可通过 GET /v1/models/{id}/ir 读取。该 IR 暂时是可审计的规划层，不改变现有稳定几何构建路径。

后续升级顺序：

1. 为 IR 建立版本化 JSON Schema/Pydantic 校验和迁移器。
2. 将 feature planner 从模型族模板扩展为可组合 Feature DAG。
3. 引入几何/装配/制造约束求解器，返回冲突解释。
4. 用面级实测与多视图视觉检查驱动 repair loop。
5. 将长任务迁移到可中断的进程级 worker，并保留每次 IR/几何/检查的 provenance。

## CAD 质量与准确度升级（2026-10-03）

已完成第一批实现：

- 支持 mm、cm、m、in 输入，统一转换到毫米并保存原始单位、换算因子和尺寸来源。
- 支持无单位三维尺寸组（例如 `120 x 80 x 42`），对直径、线缆尺寸和卡扣开口进行语义区分，避免把特征尺寸误当主体尺寸。
- 增加 `strict_dimensions` 请求选项，生产调用可以拒绝含糊尺寸。
- Semantic CAD IR 对隔板记录 requested count 与实际 divider count，并写入特征降级信息。
- 增强 OCCT/B-Rep 指标、STEP 回读、网格封闭性、单位/轴向/checksum 元数据。
- 增加 parser/IR/制造性回归测试和 GitHub Actions 质量工作流。

下一步仍需在带 CadQuery 的 Docker 环境执行多模型族导出 smoke test，并将面级壁厚、间隙、拔模和悬空测量接入质量门禁。


## 建模过程可视化（2026-10-03）

本轮把生成过程从单一 loading 状态升级为可追溯的实际事件流：

- GenerationRecorder 在解析、Semantic CAD IR 规划、每个 CadQuery 特征、几何校验、制造审查和导出时记录状态、耗时、操作和降级原因。
- 异步 job 的 progress 会在每个真实里程碑后更新，页面轮询时显示当前阶段和已完成事件；取消任务会在下一个安全边界停止。
- include_steps: true 会保存最多 6 个中间形体快照，并在能使用 trimesh 时导出 GLB；前端的步骤按钮直接加载 /v1/models/{id}/steps/{step_id}。
- 最终 generation_trace 同时写入 API 响应和 manifest，便于复盘一次生成到底执行了哪些几何操作。
- 无后端时 UI 显示离线参数化预览的本地流程；连接后端后切换为真实 CadQuery/OCCT 事件，不把等待时间伪装成完成进度。

验收标准：任务状态页能看到 queued/running/succeeded 或 failed；每个事件有稳定 id、状态和耗时；步骤预览缺失时显示可解释的降级状态；刷新页面后最终 manifest 仍保留生成轨迹。


## Family-independent Semantic CAD IR v0.2（2026-10-04）

已确定下一代建模协议：用户不选择模型族，LLM 生成版本化的“原语 + 特征 + 约束 + 基准”IR；族型仅作为可选宏编译器，最终统一进入 CadQuery/OCCT 白名单执行器。详细协议、示例、迁移步骤、API 和质量门禁见 [docs/SEMANTIC_CAD_IR.md](docs/SEMANTIC_CAD_IR.md)。

下一轮实现优先级：

1. P0：Pydantic/JSON Schema、引用/DAG/单位/范围校验、legacy → IR 适配器。
2. P1：box/cylinder/sphere/cone、布尔、变换、sketch、extrude、shell、fillet、chamfer 执行器。
3. P2：尺寸/几何/拓扑/制造约束与语义 selector。
4. P3：确定性修复配方与受限 IR patch repair loop。
5. P4：图片/草图输入和装配 component/mate。

兼容要求：现有 `POST /v1/generate`、`ModelParameters`、导出 URL 和前端预览继续可用；IR 路径必须记录 schema、IR hash、fallback 原因、执行轨迹和验证结果。


## P0/P1 实现进度（2026-10-04）

- P0 已完成：`backend/ir_schema.py`、`backend/ir_validate.py`、`backend/legacy_adapter.py`。
- 现有 `build_design_ir` 会自动升级为 v0.2，保留 `features` 兼容字段；旧 `ModelParameters`、导出和前端流程未改变。
- 新增 `POST /v1/ir/validate`，只做 JSON Schema、ID、引用、DAG、操作白名单和表达式安全检查。
- P1 已开始：`backend/ir_executor.py` 支持 box/cylinder/sphere/cone/torus/polygon_prism、sketch、extrude、revolve、union/cut/intersect、translate/rotate、shell、fillet/chamfer。
- 新增 `POST /v1/ir/compile`，在内存中执行通用 IR 并返回 B-Rep 指标与执行轨迹；CadQuery 不可用时明确返回服务不可用。
- 已覆盖参数表达式、布尔切除和草图挤出的回归测试。

下一步是将 selector、约束求解和通用 IR 生成器接入主生成路径；旧族型构建器在回归指标达标前继续作为 fallback。


## P2/P3 实现进度（2026-10-04）

- 增加 `ir_constraints.py`：解析参数表达式并评估 range/process/manufacturing 规则，区分 hard violation、soft warning 和 deferred geometry check。
- 增加语义 selector 静态校验：实体、拓扑类型和 where 属性必须来自白名单。
- 增加 `ir_repair.py` 与 `POST /v1/ir/repair`：默认只建议 `set_parameter` 等受限 patch，显式 apply 后重新验证。
- 增加 `POST /v1/ir/plan`：高级模式下让 LLM 直接生成 v0.2 IR 草案；服务端执行大小限制、JSON 校验、IR 校验和约束检查。
- 现有 `POST /v1/generate` 仍走兼容路径，通用 IR 先通过 plan/validate/compile 独立验证，待指标对齐后切换主生成策略。



## P4 实现进度（2026-10-04）

已将通用 IR 接入主生成链路：

- GenerateRequest.generation_strategy 支持 legacy、ir、auto，并纳入缓存键，避免不同执行策略复用错误结果。
- legacy 保持原有解析器和确定性构建器；ir 使用 LLM 生成并校验 Semantic CAD IR v0.2，执行约束求解、CadQuery/OCCT 编译、B-Rep 质量门和导出。
- auto（高级模式默认）先走通用 IR；LLM 未配置、IR 无效、约束失败或内核执行失败时回退 legacy，并将回退原因写入 provenance、assumptions 与 generation trace。
- 异步 jobs、步骤快照、manifest、STEP/STL/GLB/3MF 导出共用同一策略字段，前端高级模式已发送 generation_strategy=auto。
- 增加策略默认值与缓存隔离回归测试；CadQuery 不可用时 IR 编译仍返回明确的 503，而标准模式不受影响。

下一步：

- 在 Docker 中接入真实 DeepSeek Flash/兼容 API，采集 IR 成功率、回退率、内核耗时和 B-Rep 失败原因。
- 用真实模型样本扩充 primitive/feature/constraint 覆盖，并将约束修复循环接入 auto 的有限重试。


## P5 实现进度（2026-10-04）

- 自动 IR 路径在 CadQuery/OCCT 执行前接入已有约束修复器，最多尝试两轮受限参数 patch；每轮都重新验证 IR 与工艺约束。
- IR 回退原因会映射为稳定分类（LLM JSON、约束、依赖图、未支持操作、CadQuery 不可用、内核校验），便于监控和提示词反馈。
- 修复事件进入 generation trace，patch、最终约束报告进入 checks、provenance 和 manifest；修复失败仍会由 auto 策略回退 legacy。
- 通用 IR 的节点 ID 会转换为安全的步骤预览 ID，避免自然语言生成的短横线、数字或特殊字符破坏步骤 GLB 路径。
- 执行器已扩充 sweep、loft、linear_pattern、polar_pattern，并由 IR schema 提示词公开这些操作。

下一步：

- 将 IR 编译错误按节点和操作分类，形成可观测指标并用于提示词反馈。
- 完善面级选择器与 DFM 测量，并建立真实 LLM 语料回归集。


## P6 实现进度（2026-10-04）

- 导出前质量门新增包围盒实测尺寸、目标尺寸、逐轴偏差、工艺公差阈值和 dimension_match；自由形体保留偏差记录，不会因为基线尺寸代理值误阻止导出。
- 该指标与 valid_brep、OCCT 有效性、单实体、体积和导出回读并列，前端可直接显示尺寸准确度与几何有效性的区别。
- 结构化面/边 selector 已支持 index、normal、position、area、parallel_to、perpendicular_to 和 axis 基础匹配，并在无匹配时 fail-closed。
- 面级 DFM 已记录面面积、法向、中心点、下向面和保守悬空筛查；壁厚优先使用 B-Rep 面间距离，内核不提供距离 API 时回退到相对面中心代理，并记录面索引与测量方法。
- 注塑工艺按可配置拉模方向（默认 +Z）计算侧面的拔模偏差并逐面返回 pass/warning；非法方向会安全回退并标记 warning。单实体模型的装配间隙明确返回 unknown，同时保留工艺建议间隙，避免把名义值误报为验证通过。
- `POST /v1/models`、`POST /v1/jobs` 和 `POST /v1/ir/compile` 共用 `mold_pull_direction` 契约，前端在注塑工艺下提供方向选择。
- `/v1/ir/compile` 支持可选 `reference_ir` 与 `clearance_target_mm`，对两个独立 IR 实体执行 B-Rep 距离测量；缺少参考实体或内核距离 API 时返回 unknown，不伪造装配通过。
- 前端质量摘要已显示采样面数、壁厚测量、拔模状态和间隙状态；现有 selector 仍保持无匹配即失败。
- 执行 trace 与 analysis 现在返回 selector 的源/目标拓扑、命中索引和数量；前端对可见预览提供命中提示和保守整体 glow。
- GLB 导出优先按最终 OCCT 面拆分为稳定命名的 `occt_face_<index>` 节点，并在 `analysis.glb_face_mapping` 保存版本、坐标系、面索引、顶点数和三角形数；只有 selector 输入实体在最终输出中通过 OCCT 拓扑身份校验时，Three.js 才做真正的面级高亮，否则安全回退整体提示。

P6 阶段目标已完成。下一阶段：

- 引入 OCCT 射线/法向厚度采样与更严格的装配干涉检查，并扩展多实体 GLB 语义映射。


## P7 已完成切片：多实体与装配质量信号

- IR 执行器保留全部 outputs，编译结果输出 output_nodes、output_metrics，继续兼容首个 output_node。
- 参考实体距离按工艺容差区分通过、间隙不足、接触和干涉；返回 state、contact_tolerance_mm 与 interference，避免把零距离误报为普通 warning。
- 面级壁厚输出显式记录方法、置信度与法向射线采样可用性；当前没有完整射线求解器时保持保守标记。
- 已补充多输出 IR 校验和间隙状态回归测试。

P7 下一步：将多实体输出接入预览场景与选择器语义，并在 OCCT 运行环境中增加可选法向射线厚度采样。

- P7.2 已增加零距离实体的交集体积判定；贴合无公共体积显示 contact，实际相交显示 interference，无法判定时保守记录并保留方法。

## P8.2 法向厚度采样

- 已加入可选 OCP/BRepIntCurveSurface 射线采样器，从面中心沿内法向取第一有效交点并记录厚度、样本数和置信度。
- /health 暴露 occt_normal_ray_available；OCP 接口缺失或单面无有效命中时自动回退 B-Rep 面距/中心代理。
- 仍需在含 CadQuery/OCCT 的部署镜像中用真实薄壁、壳体和凹腔样本做几何回归。

- 多实体质量门已接入：编译与 IR 生成逐输出检查 B-Rep、体积、面数和单实体拓扑，任一输出失败即拒绝并返回逐实体 output_quality。

## P8.4 多实体预览产物

- 多输出 IR 生成时额外导出合并的 model_entities.glb，每个实体和 OCCT 面保持稳定节点名。
- 现有 model.glb、STEP、STL 行为保持兼容；新增 glb_entities 下载格式和 analysis.glb_output_mapping。


## P8.3 CadQuery/OCCT 运行时回归（2026-10-04）

- backend/requirements.txt 固定 cadquery==2.4.0，保证生产镜像和 CI 使用同一几何内核版本。
- backend/Dockerfile 复制所有后端 Python 模块，并安装 libgl1、libglib2.0-0、libsm6、libxext6、libxrender1，使 CadQuery/VTK 在 slim 镜像内可无桌面导入。
- backend/kernel_smoke.py 覆盖真实薄壁/凹腔 B-Rep、面级 DFM 和法向射线能力标记，以及两个独立 Semantic CAD IR 输出的质量门。
- .github/workflows/quality.yml 增加镜像构建和烟测 job；run 260 已通过，parser regression 与 kernel smoke 均为 success。

验收结论：CadQuery/OCCT 的生产式 Docker 镜像已经具备可重复的最小内核回归门禁；后续新增 IR 操作或 DFM 算法应先扩展该 smoke 样例，再合并到主分支。


## IR-first 交付状态（2026-10）

- 默认生成策略已切换为 `ir`，前端标准与高级模式都走通用 IR。
- 已注册 `regular_polygon` 原语并覆盖三角形到任意正多边形的参数化边界框。
- LLM 仅输出数据 IR；确定性规划器只处理明确原语，未知自由形体不会回退到模型族模板。
- 生成结果保留 IR、约束报告、修复尝试、执行 trace 和导出工件，便于审计与增量演进。
