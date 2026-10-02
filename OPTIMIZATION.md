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
- 无后端或 GLB 不可用时，交互提示明确标记为“概念预览/SVG 降级”，避免把预览层误认为已生成真实 3D B-Rep。
- OpenAI-compatible provider 对 response_format 不兼容时，后端仅对 400/404/422 重试一次无该字段的请求，返回仍经过同一套 JSON 与参数边界校验。
- 取消已完成但来不及中断 OCCT 的 job 时，worker 会删除刚写入的 artifact，避免取消请求造成磁盘泄漏。
- 语言切换保留 LLM 来源和 assumptions；高级 revision 恢复时优先使用原始自然语言。

尚需真实部署环境验证：不同 trimesh/Three.js 版本的坐标轴约定、WebGL 设备差异，以及运行中的 CadQuery 线程是否需要进程级 worker 隔离。
