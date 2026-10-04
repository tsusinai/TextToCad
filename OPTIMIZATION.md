# Global optimization review and execution

审查来源：6AstraMedium 全局代码审查。

## P0 — 本轮执行

- 修复后端 manifest 构造后未写入的问题，确保生成后的 manifest 可读取。
- 为 SVG 预览加入 Blender/Unity 风格的缩放、旋转、平移、适配和重置交互，支持鼠标、触摸和滚轮。
- 为生成请求加入序列号和 AbortController，旧响应不能覆盖新提示，失败时按钮和状态可以恢复。
- 让前后端识别 plant pot、lamp base、pen cup 等同一模型族，避免 UI 预览与 B-Rep 类型不一致。
- 根据实际后端 artifact 能力显示 STEP、3MF、GLB 导出按钮。
- 加入超时产物 TTL、失败产物回收、规范化提示词缓存和 STEP 导出锁，降低重复建模、磁盘增长和并发 schema 配置风险。

## P1 — 下一轮建议

- 将同步生成拆成受限 worker 的 job/status API，加入超时、取消和磁盘配额；当前已先完成 TTL 与前端取消。
- 将现有进程内 canonical spec/hash 缓存扩展为可观测的持久化缓存，目标是预览 P50 小于 1 秒、STEP P95 小于 10 秒。
- 将壁厚采样升级为面级厚度分析，并把问题定位到视图中的具体面。
- 将 clearance、overhang、draft 从参数代理升级为几何实测；未知结果显示 unknown，不显示通过。
- 区分 chamfer 和 fillet，失败时返回 degraded 或可解释的 422。

## P2 — 体验和平台

- 引入真正的 GLB viewer/OrbitControls，同时保留 SVG 离线降级。
- 统一 i18n key，接通 Workspace、Templates、History 面板和跨设备 revision。
- 增加测量、剖切、线框、面选择、轴向视图和高对比度/减少动效支持。

## 验收标准

- `GET /v1/models/{id}/manifest` 在生成后返回 200。
- 鼠标拖动、触摸拖动、滚轮缩放和重置按钮在三视图中可用。
- 新提示或新工艺提交后，旧请求不能改变当前模型。
- 同一 prompt 的前后端 kind/title 一致。
- 导出按钮只在当前 revision 实际提供对应 artifact 时启用。

## 第二轮 Astra 头脑风暴执行

- 生成请求增加 30 秒超时、取消按钮、Esc 取消、阶段状态和可恢复错误提示。
- 制造面板改为“名义估算/需复核”语义，未进行面级测量的悬空、拔模和间隙不再显示为通过。
- 前端保留模型 kind，并为花盆/笔筒显示圆柱空腔和排水孔语义；后端加入花盆排水孔和灯座底部走线槽。
- 补充视图按钮 `aria-pressed`、键盘旋转/缩放/FIT、动态 SVG 无障碍文本和移动端导出换行。

仍待后续：真实 GLB/OrbitControls、异步 job/status 队列、持久化缓存、面级厚度/间隙分析和可编辑参数卡。

## 第三轮优化执行

- 后端增加 `/v1/jobs` 创建、轮询和取消接口，并限制并发生成数；前端优先使用异步任务，旧后端自动回退到同步接口。
- 参数卡支持宽度、深度、高度、壁厚、倒角和底厚编辑，范围校验后重新生成并保留当前模型语义。
- 后端 GLB 产物接入渐进式 Three.js + OrbitControls 视图；CDN 或 GLB 不可用时自动回退 SVG 预览。

未完成项：真实面级厚度/间隙采样、持久化队列、GLB 离线打包和更完整的多指触控。

## 第四轮 LLM 优化执行

- 高级模式接入 OpenAI-compatible provider；标准模式保持离线可用。
- 后端增加提示词注入边界、HTTP(S) URL 校验、超时上限、响应字节上限、JSON 解析错误收敛和有限枚举/数值/布尔值校验。
- 前端发送原始意图与确定性基线，探测 /health 的 LLM 能力，并展示 provider 未配置时的明确状态。
- 生成响应和 manifest 保留 mode、llm_used、assumptions；LLM 永远不生成或执行 CadQuery 代码。
- 高级解析出的排水孔、底部走线槽会映射到特征树，保持意图到界面的可见性。

验收：未配置 API 时高级模式可安全回退；非法数值、NaN、错误布尔值和超大响应不会进入几何构建；前端脚本静态语法检查通过。

## Astra 第四轮审查执行

Astra 专项审查后已执行：

- GLB 替换前释放旧 geometry、material、texture，避免连续生成后 GPU 内存累积。
- 只有真实 GLB 处于可见状态时才运行 Three.js 渲染循环；隐藏或降级到 SVG 时停止循环。
- GLB fetch 使用 AbortController，快速重新生成时旧下载不会覆盖新模型。
- 生成开始立即清理旧 GLB 并渲染当前草稿，避免页面继续显示上一版实体。
- 无后端时先显示真实的 Three.js 参数化预览；只有 WebGL/CDN 不可用才进入 SVG 降级，并明确说明它不是后端校验过的 B-Rep。
- OpenAI-compatible provider 对 response_format 不兼容时，后端仅对 400/404/422 重试一次无该字段的请求，返回仍经过同一套 JSON 与参数边界校验。
- 取消已完成但来不及中断 OCCT 的 job 时，worker 会删除刚写入的 artifact，避免取消请求造成磁盘泄漏。
- 语言切换保留 LLM 来源和 assumptions；高级 revision 恢复时优先使用原始自然语言。

尚需真实部署环境验证：不同 trimesh/Three.js 版本的坐标轴约定、WebGL 设备差异，以及运行中的 CadQuery 线程是否需要进程级 worker 隔离。

## 真实 3D 预览与 Semantic CAD IR

- 无后端 GLB 时，前端通过 Three.js 根据当前参数生成真实可旋转、缩放、顶视、前视的参数化预览；SVG 仅作为 WebGL/CDN 不可用的最后降级。
- 后端新增 Semantic CAD IR v0.1，记录设计意图、参数来源、基准面、特征 DAG 初稿和约束，并写入 manifest。
- 新增 GET /v1/models/{id}/ir，供审查、版本回溯和下一阶段约束求解使用。


## Astra 全局审查与本轮修复（2026-10）

Astra 对 README、前端 3D/LLM 交互、CadQuery/OCCT 后端、Docker 和 DeepSeek 配置做了只读全局审查，本轮已执行：

- `/v1/*` 支持通过 `BACKEND_API_KEY` 开启 `X-API-Key` 鉴权；`/health` 保持可用于探针。
- 异步任务增加 `MAX_PENDING_JOBS` 队列上限，满载返回 429；生成 mutation 增加按客户端地址的时间窗口限流，并在健康信息中公开并发/队列/限流配置。
- LLM key 读取会去除空白；结构化响应加入 schema version 检查，非法特征组合会归一化并记录 assumptions。
- 制造性分析明确标记为 nominal，并增加 `review_required`；warning 不再被误解为面级制造认证。
- 前端统一携带可选 API key，并使用带鉴权的二进制下载，受保护后端仍能加载 GLB 和导出文件。
- Docker Compose 的 `backend/.env` 改为可选，首次启动不再因缺少本地密钥文件直接失败。
- README、后端 README 和 DEPLOY 补齐 Standard/Advanced、3D 预览降级、异步 API、IR、DeepSeek、HTTPS 和生产安全边界。

仍需真实部署验证：Docker Compose 版本对 optional `env_file` 的支持、WebGL/Three.js 设备差异，以及多副本环境下的共享队列和持久化存储。

## 建模质量提升执行（2026-10-03）

Astra 建模质量专项建议已落实第一批 P0/P1：

- 单位解析支持 `mm/cm/m/in`，带显式换算 provenance；`strict_dimensions` 可阻止含糊尺寸静默采用默认值。
- 三维尺寸组和圆柱直径进入明确语义路径，线缆/开口/直径等特征尺寸不会再直接变成主体宽度。
- 质量门增加 OCCT analyzer、零面积面检查、STEP re-import、网格封闭性和 artifact checksum/轴向元数据。
- IR 记录隔板请求数量与实际生成数量，前端本地预览和后端单位契约同步。
- 新增 `backend/test_quality.py` 与 `.github/workflows/quality.yml`。

限制：本轮没有在当前执行环境启动 Docker/CadQuery；必须在目标主机执行完整导出 smoke test 和多设备 GLB 坐标验证。

## 建模过程展示执行（2026-10-03）

- 后端用 `GenerationRecorder` 记录真实解析、特征构建、校验、制造审查和导出事件，异步任务通过 `progress` 实时返回当前步骤。
- 前端新增建模过程面板，显示每个事件的状态与耗时；`include_steps=true` 时可从实际中间 GLB 快照打开步骤预览。
- 最终 `generation_trace` 写入响应和 manifest，便于审查实际执行链；后端不可用时显示明确的本地离线流程。
- GitHub Actions 的 Backend quality 在本轮提交后通过；gh-pages 已同步并由 Pages deployment 发布。


## 通用 IR 主链路与质量门（2026-10-04）

- 高级模式通过 generation_strategy=auto 进入 LLM → Semantic CAD IR v0.2 → 约束求解/有限修复 → CadQuery/OCCT；失败自动回退 legacy，并在 provenance 记录 fallback_reason 与稳定分类。
- IR 不再要求固定模型族，支持原语、草图、拉伸、旋转、扫掠、放样、布尔、阵列和约束；普通/锐边正方体若未明确圆角或倒角会拒绝隐式 edge treatment。
- 生成过程、修复尝试、节点步骤预览、实测包围盒和逐轴尺寸偏差进入响应与 manifest；前端显示实际生效策略，区分通用 IR 成功与旧构建器回退。
- Backend quality CI 已通过；当前主链路继续保留 legacy/IR/auto 三种策略，并把实际生效策略写入 provenance。


## P6 拓扑选择与面级 DFM（2026-10-04）

- IR selector 已接入 OCCT/CadQuery shape，支持 index、normal、position、area、parallel_to、perpendicular_to、axis；圆角、倒角和 shell 可使用结构化面/边选择器。
- 选择器无匹配或拓扑类型不适配时 fail-closed，执行 trace 保留 selector 请求，auto 策略可按 selector_resolution 回退。
- 质量门新增面面积、中心点、法向、下向面、悬空初筛以及前端采样摘要；壁厚优先使用 B-Rep 面间距离并记录面索引/方法，内核不支持时回退相对面中心代理。
- 注塑工艺按可配置拉模方向（默认 +Z）逐面计算拔模偏差；POST /v1/models、/v1/jobs、/v1/ir/compile 和前端注塑控件共用同一向量契约。
- `/v1/ir/compile` 支持可选 mating `reference_ir` 与 `clearance_target_mm`，通过 B-Rep shape distance 返回两个实体的间隙和测量方法；缺少参考实体或内核 API 时保持 unknown。
- GLB 预览优先输出 `occt_face_<index>` 节点和 `analysis.glb_face_mapping`，Three.js 可以按 selector 命中索引进行真实面级高亮；不可用时保留整体提示并明确降级。
- P6 验收目标已完成；下一阶段聚焦 OCCT 射线厚度、干涉检查和多实体语义映射。
