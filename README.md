# TextToCad

自然语言驱动的参数化 CAD 工作台：用一句话描述零件，得到可检查、可回溯、可导出的 3D 模型。

<p align="center">
  <a href="https://tsusinai.github.io/TextToCad/">打开 Live 工作台</a> ·
  <a href="https://github.com/tsusinai/TextToCad/tree/main/backend">查看几何后端</a> ·
  <a href="PLAN.md">查看路线图</a> ·
  <a href="docs/SEMANTIC_CAD_IR.md">查看通用 CAD IR 方案</a>
</p>

| 能力 | 当前实现 |
| --- | --- |
| 自然语言 | 中文/英文尺寸、单位换算、通用 Semantic CAD IR 规划、隔间、壁厚、倒角、排水孔、走线槽 |
| 3D 预览 | Three.js 参数化预览、GLB/OrbitControls、等距/顶视/前视、X/Y/Z 90° 旋转反转、XY/XZ/YZ 平面镜像与翻转、一键姿态重置 |
| 几何内核 | CadQuery/OCCT 参数化 B-Rep |
| 导出 | STEP、STL，条件支持 3MF、GLB；前端保留 OBJ 概念导出 |
| 制造检查 | FDM、SLA、CNC、注塑工艺配置，B-Rep、实体、体积、包围盒和名义壁厚检查 |
| 高级模式 | OpenAI-compatible LLM、DeepSeek 示例、受限 JSON、失败回退 |
| 可追溯性 | manifest、Semantic CAD IR、逐字段 provenance、assumptions、revision history |
| 通用建模路线 | 原语 + 特征 + 约束 + 基准的族型无关 IR（方案见 docs/SEMANTIC_CAD_IR.md） |
| 建模过程 | 异步 job 实时阶段、真实 CAD 特征事件、导出校验状态、中间 GLB 步骤预览 |

## Live 预览

访问 [https://tsusinai.github.io/TextToCad/](https://tsusinai.github.io/TextToCad/)。

没有连接后端时，页面仍会创建真实的 Three.js 参数化预览；如果浏览器不支持 WebGL 或 CDN 加载失败，才退回 SVG 概念图。连接后端后，经过 OCCT 校验的 GLB 会替换本地预览。 后端同时提供 `/v1/ir/validate` 静态校验和 `/v1/ir/compile` 通用 IR 编译接口，当前支持原语、布尔、参数表达式、变换、挤出与基础边处理。 高级模式可通过 `/v1/ir/plan` 让 LLM 生成族型无关的 v0.2 IR，并通过 `/v1/ir/repair` 获取受限修复建议。生成过程中，左侧 **BUILD PROCESS / 建模过程** 会显示后端实际完成的解析、特征构建、几何校验、制造审查和导出事件；当 CadQuery 导出中间快照可用时，可以直接点击 **VIEW STEP / 查看步骤** 在 3D 视图中检查该阶段。

## 本机启动：Docker + CadQuery + DeepSeek

项目已经提供 Docker Compose 配置。先准备本地密钥文件：

~~~bash
git clone https://github.com/tsusinai/TextToCad.git
cd TextToCad
cp backend/.env.example backend/.env
~~~

编辑 backend/.env：

~~~env
LLM_API_KEY=你的_DEEPSEEK_API_KEY
LLM_API_URL=https://api.deepseek.com/chat/completions
LLM_MODEL=deepseek-chat
LLM_TIMEOUT_SECONDS=20
LLM_MAX_RESPONSE_BYTES=65536
~~~

如果你的 DeepSeek Flash 网关使用不同的 OpenAI-compatible 地址或模型名，只替换 LLM_API_URL 和 LLM_MODEL。backend/.env 已被 .gitignore 排除，不要提交它。

启动几何服务：

~~~bash
docker compose up --build -d
curl http://localhost:8787/health
~~~

健康检查应包含 cadquery_available=true；配置密钥后还应包含 advanced_mode_available=true 和安全的 llm_provider 字段。

启动静态前端：

~~~bash
python3 -m http.server 5173
~~~

打开 [http://localhost:5173/](http://localhost:5173/)。本机页面会自动尝试连接 http://localhost:8787；也可以显式传入：

~~~text
http://localhost:5173/?backend=http://localhost:8787
~~~

## 从文字到 CAD 的链路

~~~mermaid
flowchart LR
  A[自然语言<br/>中文 / English] --> B[规则解析或 LLM 意图解析]
  B --> C[Design Contract<br/>受限参数与 assumptions]
  C --> D[Semantic CAD IR<br/>参数 / 特征 / 约束]
  D --> E[CadQuery / OCCT<br/>确定性 B-Rep]
  E --> F[几何与制造检查]
  F --> G[STEP / STL / 3MF / GLB]
  G --> H[Three.js 交互预览]
~~~

LLM 只负责理解设计意图，不生成或执行 CadQuery 代码。后端会把 mm/cm/m/in 统一换算为毫米，记录原始单位和逐字段来源，对 IR 参数、特征操作、选择器、尺寸、布尔值、数值范围和响应大小做校验，再交给 CadQuery/OCCT 建模；旧模型族只作为兼容提示，不限制新描述。没有 API key、provider 超时、JSON 无效或 provider 不支持 JSON response format 时，会回退到确定性解析器。

## 纯自然语言驱动与无模板通用 CAD 架构

系统已彻底解除对固定模板族的强依赖，实现纯自然语言到可制造 CAD 实体的端到端编译与渲染：

1. **纯自然语言直通规划**：用户输入任意形式的几何与制造描述（如“带穿孔圆柱套筒”、“中心挖球形空腔的立方体”、“法兰底座与上凸台及中心通孔”），系统直接通过 LLM 或通用解析器生成无族型约束的 `Semantic CAD IR v0.2`。
2. **多特征与 CSG 布尔运算**：IR 执行器全面支持图原语（`box`, `cylinder`, `sphere`, `cone`, `torus`, `regular_polygon`, `sketch`）及其空间位移（`position/translate`）、旋转（`rotate`）、镜像（`mirror`），以及核心 CSG 布尔操作（`cut` 差集开孔/切削、`union` 并集组合、`intersect` 交集），并结合倒角（`chamfer`）、圆角（`fillet`）和抽壳（`shell`）。
3. **真实 3D 视口渲染与交互姿态控制**：CadQuery/OCCT 内核完成 B-Rep 实体构建后生成标准 GLB 产物；前端 Three.js 视口直接加载渲染 3D 实体与 CAD 轮廓线框，不仅支持轨道旋转、平移、缩放、正视/顶视/等轴测多视角切换与视野自适应，还全新集成了 **X/Y/Z 轴 90° 旋转反转、XY/XZ/YZ 平面镜像（双面材质渲染防破损）、XY/XZ/YZ 平面 180° 翻转及一键姿态重置** 工具栏，方便多角度审查与倒装检查。
4. **动态参数化特征树**：前端工作台直观展示 IR 特征图执行流（例如 `CYLINDER · outer` → `CYLINDER · hole` → `CUT · through-hole`），并实时呈现基于 B-Rep 拓扑的水密实体指标（面数、体积、三维空间包围盒），确保设计完全透明可回溯。

## 典型示例（非固定模型族）

- Storage tray / organizer：托盘、桌面收纳盒、隔间（示例）
- Cable clip：线缆夹和开口结构
- Plant pot：花盆、圆柱腔体、排水孔
- Lamp base：灯座和底部隐藏走线槽
- Pen cup：笔筒和圆柱腔体
- Solid block：通用实体块
- L bracket：L 形支架、直角折条，支持两条腿尺寸与板厚（示例）
- Generic IR：任意原语、草图、拉伸、旋转、布尔、阵列和约束组合；未列出的形体不会被强制归入这些示例。

## API 快速参考

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /health | CadQuery、GLB、LLM 配置状态 |
| GET | /v1/process-profiles | FDM、SLA、CNC、注塑工艺约束 |
| POST | /v1/models | 同步生成一个模型（默认通用 IR 模式） |
| POST | /v1/jobs | 创建可轮询、可取消的生成任务 |
| GET/DELETE | /v1/jobs/{job_id} | 查询或取消任务 |
| GET | /v1/models/{id}/steps/{step_id} | 查看 `include_steps=true` 生成的中间 GLB |
| GET | /v1/models/{id}/manifest | 参数、检查、导出和 provenance |
| GET | /v1/models/{id}/ir | Semantic CAD IR |
| GET | /v1/models/{id}/analysis | 壁厚采样和制造问题 |
| GET | /v1/models/{id}/download?format=step | 下载 STEP、STL、3MF 或 GLB |
| POST | /v1/ir/plan | 自然语言编译为通用 v0.2 IR 草案 |
| POST | /v1/ir/validate | 静态校验 IR 语法、DAG、原语和约束 |
| POST | /v1/ir/compile | 内存直接编译执行通用 IR |
| POST | /v1/ir/repair | 生成受限 IR 参数修复补丁 |

异步任务的 `GET /v1/jobs/{job_id}` 响应会返回 `progress.stage`、`current_step`、`elapsed_ms` 和有序 `events`；最终 response 与 `manifest.json` 也会保存 `generation_trace`。前端因此展示真实后端阶段，而不是按时间猜测进度。请求加入 `include_steps: true` 后，后端会保存有限数量的中间 GLB 快照。

严格尺寸请求示例（遇到无标签尺寸时返回 422）：

~~~json
{
  "prompt": "block 120 80",
  "units": "mm",
  "strict_dimensions": true,
  "mode": "advanced",
  "generation_strategy": "ir"
}
~~~

纯自然语言请求示例：

~~~json
{
  "prompt": "A cylinder with radius 16 mm and height 35 mm, with a through-hole of radius 6 mm along the central axis",
  "units": "mm",
  "process": "fdm",
  "mode": "standard",
  "generation_strategy": "ir"
}
~~~

## 为什么采用混合架构

直接让 LLM 生成 CAD 代码或网格，容易出现单位混乱、拓扑失效、不可制造和无法复现。TextToCad 把系统拆成两层：

1. LLM/规则解析层：理解意图，生成受限参数和假设。
2. 几何确定层：由 Semantic CAD IR、CadQuery/OCCT、验证器和导出器完成实际建模。

每个 revision 会保存参数来源、assumptions、特征规划、约束、检查和导出 manifest。IR 已支持版本化 Schema、Feature DAG、约束求解器、有限自动修复、面级 DFM、sweep/loft/pattern 与 CSG 布尔差运算。

## 当前边界

- 壁厚、间隙和拔模仍包含名义估算；当前已增加面面积、法向、中心点和下向面的保守悬空初筛。`manufacturing_ready` 会保持 false。
- 未配置 LLM API Key 时，支持显式原语及通孔布尔运算的离线生成；任意未知自由形体在无 LLM 时返回 503，避免错误映射到固定模板。
- 没有后端时可以进行真实参数化预览和 OBJ 概念导出，但 STEP/STL/OCCT 检查必须连接后端。
- 生产部署应使用 HTTPS、持久化 ARTIFACT_ROOT、严格 CORS、速率限制和进程级任务隔离。

## 安全与生产部署

本地 Docker 默认不要求 API key，便于快速试用。公网部署请在 `backend/.env` 设置 `BACKEND_API_KEY`；之后所有 `/v1/*` 请求都必须携带 `X-API-Key`，前端可在加载页面前注入 `window.FORM_CAD_BACKEND_API_KEY`。不要把密钥写进 GitHub Pages 仓库，生产环境应使用 HTTPS、反向代理鉴权、严格 CORS、持久化 `ARTIFACT_ROOT` 和监控。

异步生成队列有进程内上限，满载时返回 HTTP 429；生成接口还按客户端地址限制单位时间内的创建次数。当前缓存和任务状态也是进程内的，Docker 使用单 worker；多副本部署需要外部队列和共享存储。GitHub Pages 连接远程后端时只能使用 HTTPS，`http://localhost` 仅用于同一台机器上的本机调试。


## 文档

- [DEPLOY.md](DEPLOY.md)：Docker、DeepSeek 和前端连接
- [PLAN.md](PLAN.md)：阶段计划和 Semantic CAD IR 升级路线
- [OPTIMIZATION.md](OPTIMIZATION.md)：Astra 审查与执行记录
- [backend/README.md](backend/README.md)：后端 API 和开发说明


## 质量回归

后端包含单位、尺寸语义、特征尺寸过滤、IR 特征计数和制造评估的回归测试；推送到 GitHub 后会由 Actions 自动运行。CadQuery/OCCT 导出回读则在 Docker 环境中执行。


### 几何内核回归

后端镜像现在固定安装 CadQuery 2.4，并复制完整 IR 执行模块。CI 会构建同一镜像并运行 backend/kernel_smoke.py，覆盖薄壁实体、面级厚度分析、法向射线能力标记和多输出 IR。
