# Semantic CAD IR v0.2 方案

## 目标

把“自然语言 → 固定模型族 → 参数 → CadQuery”升级为：

```
自然语言 / 图片 / 草图
        ↓
需求契约（Design Contract）
        ↓
Semantic CAD IR：原语 + 特征 + 约束 + 基准
        ↓
约束归一化与求解
        ↓
Feature DAG 执行器
        ↓
CadQuery / OCCT B-Rep
        ↓
几何、制造、视觉验证与修复
```

用户不需要选择模型族。模型族识别可以作为内部的可选提示或宏编译器，但最终 IR 不包含“必须属于某个族”的约束。任何对象只要能够被表达成受限原语和特征，就可以进入同一条执行链。

## 当前实现的耦合点

当前后端的 `parse_prompt_detailed`、`interpret_prompt` 和 `build_geometry` 共同依赖 `params.kind`。这会带来三个问题：

1. 新对象必须增加解析分支、标题映射、前端预览分支和 CadQuery 分支。
2. LLM 只能在有限枚举中选择，未知物体会退化成 block。
3. 约束和特征没有独立的拓扑引用，难以表达“在某个面上开孔”“沿边阵列”“与另一实体保持间隙”。

v0.2 保留 `ModelParameters` 作为兼容响应，但将 `design_ir` 变成新的生成事实来源。旧的族型解析器通过适配器生成 IR，不能反向限制 IR 的能力。

## IR 顶层结构

```json
{
  "schema_version": "0.2",
  "document": {
    "id": "revision-id",
    "intent": "protect a small electronic board",
    "language": "zh-CN",
    "units": "mm"
  },
  "parameters": {
    "body_length": {"value": 120, "unit": "mm", "source": "user", "role": "dimension"},
    "wall": {"value": 2.4, "unit": "mm", "source": "derived", "role": "manufacturing"}
  },
  "datums": [
    {"id": "xy", "type": "plane", "origin": [0, 0, 0], "normal": [0, 0, 1]},
    {"id": "center_axis", "type": "axis", "origin": [0, 0, 0], "direction": [0, 0, 1]}
  ],
  "nodes": [
    {
      "id": "outer",
      "kind": "primitive",
      "operation": "box",
      "parameters": {"size": ["body_length", 80, 42]},
      "frame": "xy"
    },
    {
      "id": "cavity",
      "kind": "feature",
      "operation": "shell",
      "inputs": ["outer"],
      "parameters": {"thickness": "wall", "open_faces": ["top"]}
    }
  ],
  "constraints": [
    {"id": "wall_min", "type": "manufacturing", "target": "wall", "operator": ">=", "value": 1.2, "hard": true},
    {"id": "cavity_inside", "type": "topology", "target": "cavity", "relation": "inside", "reference": "outer", "hard": true}
  ],
  "outputs": [
    {"id": "main_solid", "node": "cavity", "format": ["step", "stl", "glb"]}
  ],
  "provenance": {
    "prompt": "...",
    "parser": "llm",
    "assumptions": [],
    "generator": "TextToCad IR compiler 0.2"
  }
}
```

### 原语

第一批原语保持小而稳定：

- `box`、`cylinder`、`sphere`、`cone`、`torus`
- `polygon_prism`、`profile`
- `sketch`（line、arc、circle、rectangle、polygon）
- `component`（装配阶段使用）

所有原语都必须有稳定的 `id`、输入基准、参数引用和单位。参数可以是常数、参数名或受限表达式，例如 `body_length - 2 * wall`。不允许表达式调用 Python、CadQuery 或任意外部函数。

### 特征

特征是可组合的 DAG 节点，不以物体名称命名：

- 构造：`extrude`、`revolve`、`sweep`、`loft`
- 布尔：`union`、`cut`、`intersect`
- 薄壁：`shell`
- 边处理：`fillet`、`chamfer`
- 重复：`linear_pattern`、`polar_pattern`、`mirror`
- 变换：`translate`、`rotate`、`align`
- 检查：`clearance_check`、`single_solid_check`、`interference_check`

每个特征只引用已经存在的节点或基准，执行顺序由依赖图决定，禁止隐式的全局状态。

### 约束

约束分为四类，并带有 `hard`、`soft`、`derived` 和来源信息：

- 尺寸：长度、半径、角度、比例、对称、范围。
- 几何：平行、垂直、相切、同心、共面、对齐。
- 拓扑：在某个实体内、与某个面相交、保持单实体、不可自交。
- 制造：最小壁厚、间隙、拔模、悬垂、刀具可达性、打印方向。

约束冲突必须返回可读的冲突集，例如“`wall=0.8` 与 FDM 最小壁厚 1.2 mm 冲突”，而不是静默改值。

### 稳定引用

不要依赖 CadQuery 的临时面编号。IR 使用语义选择器：

```json
{
  "selector": {
    "entity": "outer",
    "topology": "face",
    "where": [
      {"normal": [0, 0, 1]},
      {"position": [0, 0, 42]}
    ]
  }
}
```

执行器将选择器解析成当前 OCC shape 的面、边或顶点集合；支持 index、normal、position、area、parallel_to、perpendicular_to 和 axis 基础匹配。没有匹配或拓扑类型不适配时会 fail-closed，并在 generation trace 中报告 selector_resolution。

## LLM 输出契约

LLM 只负责把自然语言转为 IR 草案，不输出 CadQuery、Python 或任意可执行代码。输出必须符合版本化 JSON Schema：

```json
{
  "schema_version": "0.2",
  "document": {},
  "parameters": {},
  "datums": [],
  "nodes": [],
  "constraints": [],
  "outputs": [],
  "assumptions": [],
  "provenance": {}
}
```

服务端按以下顺序处理：

1. JSON 解析、大小限制和字段白名单。
2. Pydantic/JSON Schema 校验。
3. ID 唯一性、引用存在性、DAG 无环检查。
4. 单位归一化和参数范围检查。
5. 约束求解与冲突解释。
6. 只允许白名单执行器调用 CadQuery。
7. B-Rep、实体数量、体积、包围盒和制造检查。
8. 失败时生成受限 IR patch，而不是重新生成整段代码。

LLM patch 只允许这些操作：`set_parameter`、`replace_node_parameter`、`add_node`、`remove_node`、`replace_constraint`。patch 必须引用现有 ID，并在每次修复后重新校验。

## 不使用固定模型族的示例

### 杯子

杯子不需要 `kind = cup`：

1. `outer`: cylinder。
2. `inner`: cylinder，引用 `wall` 和 `bottom`。
3. `body`: cut(`outer`, `inner`)。
4. `handle_profile`: sketch + arc。
5. `handle`: sweep 或 torus。
6. `result`: union(`body`, `handle`)。
7. 约束：开口朝上、壁厚不低于工艺下限、握柄与杯壁相交、最终单实体。

### 飞机

飞机也只是特征组合：

1. `fuselage`: cylinder 或 loft。
2. `wing_profile`: sketch。
3. `wing`: extrude。
4. `tail_profile`: sketch。
5. `tail`: extrude。
6. `result`: union(`fuselage`, `wing`, `tail`)。
7. 约束：机翼与机身相交、左右对称、尾翼位于机身后段、最终单实体。

族型模板可以把上面的组合封装成宏，加快常见对象的生成，但宏必须编译成同一套 IR，不能成为执行器的特殊分支。

## 后端模块拆分

建议把当前单体 `app.py` 拆成以下模块；第一阶段可以仍放在一个文件中，接口先稳定：

- `ir_schema.py`：版本化 Pydantic 模型、枚举和 JSON Schema。
- `ir_validate.py`：引用、DAG、单位、范围和约束静态检查。
- `ir_solver.py`：参数表达式、几何约束和制造约束求解。
- `ir_selectors.py`：语义面/边/顶点选择器到 OCCT shape 的解析。
- `ir_executor.py`：原语和特征到 CadQuery 的白名单映射。
- `ir_repair.py`：确定性修复配方和受限 LLM patch。
- `legacy_adapter.py`：当前 `ModelParameters`、旧 `kind` 和 v0.1 IR 的兼容转换。
- `app.py`：API、任务、缓存、导出和响应编排。

## 迁移路线

### P0：协议和兼容层

- 定义 `schema_version=0.2` 的 Pydantic/JSON Schema。
- 实现 legacy → IR 适配器。
- 保留现有 `GenerateResponse.parameters` 和导出 URL。
- 为 IR 增加静态校验端点：`POST /v1/ir/validate`。
- 旧模型族路径与 IR 路径做同一输入的指标对比。

验收：旧测试全部通过；旧模型的 bbox、体积误差分别不超过 0.5% 和 1%。

### P1：原语和基础特征执行器

- 先实现 box、cylinder、sphere、cone、union、cut、intersect、translate、rotate。
- 再实现 sketch、extrude、revolve、shell、fillet、chamfer。
- 每个操作生成真实的 generation trace 和中间快照。
- 不再在 `build_geometry` 中新增对象名称分支。

验收：杯子、飞机、收纳盒都通过通用 IR 生成，并且不读取 `kind`。

### P2：约束与语义引用

- 实现尺寸表达式、对称、共面、相交、单实体和制造壁厚约束。
- 实现语义 selector 和拓扑引用失效报告。
- 约束失败返回冲突集和建议修复。

验收：修改一个尺寸后，相关特征增量重建；冲突不会被静默覆盖。

### P3：Repair loop

- 几何无效时先尝试确定性修复：缩小圆角、增加间隙、修正布尔顺序、延长相交长度。
- 再让 LLM 仅返回 IR patch。
- 最多两轮自动修复，保留每一轮 IR、日志和验证指标。

验收：修复成功率、失败原因和耗时进入 manifest；最终结果不能绕过验证。

### P4：更多输入与装配

- 图片/草图作为需求证据，LLM 输出带置信度的尺寸和拓扑假设。
- 支持 component、mate、interference 和 BOM。
- 引入视觉检查器比较多视图渲染与 IR 语义。

## API 与兼容策略

当前同步主接口是 `POST /v1/models`，异步主接口是 `POST /v1/jobs`；两者都接受：

- `generation_strategy: "legacy" | "ir" | "auto"`，默认 `legacy`；前端高级模式发送 `auto`。
- `design_ir` 返回最终 v0.2 IR，manifest 同时保存修复历史、执行 trace 和 fallback provenance。
- `POST /v1/ir/validate` 只做静态验证，不启动 CadQuery。
- `POST /v1/ir/compile` 在内存中执行约束与 CadQuery 编译并返回 metrics、face_measurements 和 trace，不写模型 artifact；面级 DFM 会明确区分 B-Rep 面距离、代理值、拔模方向和间隙 unknown。请求可携带 `mold_pull_direction: [x, y, z]`，用于注塑拔模检查；同时可传 `reference_ir` 与 `clearance_target_mm`，对两个实体执行真实间隙测量。
- `GET /v1/models/{id}/ir` 返回生成结果中的最终 IR；完整修复与执行信息通过 manifest 获取。

`auto` 策略先尝试 IR；IR 校验、约束修复或执行失败时，可以回退到 legacy 路径。响应的 `provenance` 同时写入 `requested_strategy=auto`、`effective_strategy=legacy`、稳定字段 `fallback_reason`（以及兼容字段 `ir_fallback_reason`），不能把回退结果伪装成 IR 成功。

## 性能、质量和安全门禁

- LLM 只在请求选择 ir/auto 且需要语义补全时调用；legacy 标准路径可离线生成。
- IR 校验、参数求解和基础原语尽量进程内完成。
- 每个任务设置 LLM 超时、输出字节上限、节点数上限、深度上限和修复轮数上限。
- 禁止任意代码、任意模块、文件路径、网络 URL 和未注册操作。
- 记录 parse、validate、solve、build、verify、repair 各阶段耗时。
- 质量指标：IR 校验通过率、B-Rep 有效率、单实体率、体积/包围盒回归误差、修复率、平均延迟、LLM 成本、导出成功率。
- 每次导出写入 schema 版本、IR hash、参数 hash、构造器版本和验证结果。

## 推荐结论

不要把“完全没有模型族识别”作为目标。应把模型族识别降级为可选的宏/提示层，把通用 IR 设为唯一执行协议。这样既能保留常见物体的速度和质量，也能让新物体通过原语、特征和约束进入同一条可验证的 CadQuery/OCCT 链路。


## P7：多输出与装配关系

- outputs 可声明多个实体；IR 执行器保留全部输出，同时继续以第一个输出兼容旧版 shape / output_node 字段。
- POST /v1/ir/compile 返回 output_nodes、output_metrics，每个输出包含独立的 B-Rep 指标；参考 IR 同样返回 reference_output_metrics。
- 传入 reference_ir 时，clearance 会区分 pass、warning、contact 和 interference，并返回 state、contact_tolerance_mm、interference、测量方法。没有参考实体或距离 API 时保持 unknown。
- 面级壁厚分析现在显式返回 wall_thickness_analysis：记录 B-Rep 面距离或相对面中心代理、置信度和 normal_ray_sampling=not_available。这避免把代理测量误报为完整法向射线厚度。

- 当距离落在内核零容差内，编译接口会尝试计算 B-Rep 布尔交集体积：可证明公共体积时标为 interference；零公共体积则标为 contact；内核不支持交集时保持保守的 interference 解释并记录方法。

- P8.2 增加可选 OCCT 法向射线采样；运行时若 OCP 射线接口可用，face sample 会带 normal_ray_thickness_mm，wall_thickness_analysis.status=ray_sampled，并在 /health 暴露 occt_normal_ray_available。不可用时仍安全回退到代理。

- 多输出编译会逐实体执行 B-Rep 质量门；任一输出没有有效 B-Rep、正体积、面或单实体拓扑时整体编译返回 422，并附 output_quality.entities 逐项原因。
