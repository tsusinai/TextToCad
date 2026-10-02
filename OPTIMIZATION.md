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
