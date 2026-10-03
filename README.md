# TextToCad

自然语言驱动的参数化 CAD 工作台：用一句话描述零件，得到可检查、可回溯、可导出的 3D 模型。

<p align="center">
  <a href="https://tsusinai.github.io/TextToCad/">打开 Live 工作台</a> ·
  <a href="https://github.com/tsusinai/TextToCad/tree/main/backend">查看几何后端</a> ·
  <a href="PLAN.md">查看路线图</a>
</p>

| 能力 | 当前实现 |
| --- | --- |
| 自然语言 | 中文/英文尺寸、mm/cm/m/in 单位换算、模型族、隔间、壁厚、倒角、排水孔、走线槽 |
| 3D 预览 | Three.js 参数化预览、GLB/OrbitControls、等距/顶视/前视、旋转/缩放/平移 |
| 几何内核 | CadQuery/OCCT 参数化 B-Rep |
| 导出 | STEP、STL，条件支持 3MF、GLB；前端保留 OBJ 概念导出 |
| 制造检查 | FDM、SLA、CNC、注塑工艺配置，B-Rep、实体、体积、包围盒和名义壁厚检查 |
| 高级模式 | OpenAI-compatible LLM、DeepSeek 示例、受限 JSON、失败回退 |
| 可追溯性 | manifest、Semantic CAD IR、逐字段 provenance、assumptions、revision history |
| 建模过程 | 异步 job 实时阶段、真实 CAD 特征事件、导出校验状态、中间 GLB 步骤预览 |

## Live 预览

访问 [https://tsusinai.github.io/TextToCad/](https://tsusinai.github.io/TextToCad/)。

没有连接后端时，页面仍会创建真实的 Three.js 参数化预览；如果浏览器不支持 WebGL 或 CDN 加载失败，才退回 SVG 概念图。连接后端后，经过 OCCT 校验的 GLB 会替换本地预览。生成过程中，左侧 **BUILD PROCESS / 建模过程** 会显示后端实际完成的解析、特征构建、几何校验、制造审查和导出事件；当 CadQuery 导出中间快照可用时，可以直接点击 **VIEW STEP / 查看步骤** 在 3D 视图中检查该阶段。

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

LLM 只负责理解设计意图，不生成或执行 CadQuery 代码。后端会把 mm/cm/m/in 统一换算为毫米，记录原始单位和逐字段来源，对模型族、尺寸、布尔值、数值范围和响应大小做校验，再交给 CadQuery/OCCT 建模。没有 API key、provider 超时、JSON 无效或 provider 不支持 JSON response format 时，会回退到确定性解析器。

## 支持的模型族

- Storage tray / organizer：托盘、桌面收纳盒、隔间
- Cable clip：线缆夹和开口结构
- Plant pot：花盆、圆柱腔体、排水孔
- Lamp base：灯座和底部隐藏走线槽
- Pen cup：笔筒和圆柱腔体
- Solid block：通用实体块
- L bracket：L 形支架、直角折条，支持两条腿尺寸与板厚

## API 快速参考

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /health | CadQuery、GLB、LLM 配置状态 |
| GET | /v1/process-profiles | FDM、SLA、CNC、注塑工艺约束 |
| POST | /v1/models | 同步生成一个模型 |
| POST | /v1/jobs | 创建可轮询、可取消的生成任务 |
| GET/DELETE | /v1/jobs/{job_id} | 查询或取消任务 |
| GET | /v1/models/{id}/steps/{step_id} | 查看 `include_steps=true` 生成的中间 GLB |
| GET | /v1/models/{id}/manifest | 参数、检查、导出和 provenance |
| GET | /v1/models/{id}/ir | Semantic CAD IR |
| GET | /v1/models/{id}/analysis | 壁厚采样和制造问题 |
| GET | /v1/models/{id}/download?format=step | 下载 STEP、STL、3MF 或 GLB |

异步任务的 `GET /v1/jobs/{job_id}` 响应会返回 `progress.stage`、`current_step`、`elapsed_ms` 和有序 `events`；最终 response 与 `manifest.json` 也会保存 `generation_trace`。前端因此展示真实后端阶段，而不是按时间猜测进度。请求加入 `include_steps: true` 后，后端会保存有限数量的中间 GLB 快照。

严格尺寸请求示例（遇到无标签尺寸时返回 422）：

~~~json
{
  "prompt": "block 120 80",
  "units": "mm",
  "strict_dimensions": true
}
~~~

高级模式请求示例：

~~~json
{
  "prompt": "一个带三个隔间、宽 120 毫米、深 80 毫米的桌面收纳盒",
  "units": "mm",
  "process": "fdm",
  "mode": "advanced"
}
~~~

## 为什么采用混合架构

直接让 LLM 生成 CAD 代码或网格，容易出现单位混乱、拓扑失效、不可制造和无法复现。TextToCad 把系统拆成两层：

1. LLM/规则解析层：理解意图，生成受限参数和假设。
2. 几何确定层：由 Semantic CAD IR、CadQuery/OCCT、验证器和导出器完成实际建模。

每个 revision 会保存参数来源、assumptions、特征规划、约束、检查和导出 manifest。后续可以在 IR 上加入版本化 JSON Schema、Feature DAG、约束求解器、面级 DFM 检查和自动修复闭环。

## 当前边界

- 壁厚、间隙、悬空和拔模目前包含名义估算；真正的面级测量仍是下一阶段。`manufacturing_ready` 会保持 false。
- LLM 高级模式需要后端 API key；标准模式无需 API，仍可离线工作。
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
