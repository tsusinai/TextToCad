# TextToCad geometry backend

This service turns a natural-language part description into a validated parametric B-Rep with CadQuery/OCCT. The LLM, when enabled, only produces a constrained design intent; the geometry boundary remains deterministic and auditable.

## Run locally

~~~bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8787
~~~

The API is available at `http://localhost:8787`. For the recommended Docker path, see [../DEPLOY.md](../DEPLOY.md).

~~~bash
curl -X POST http://localhost:8787/v1/models \
  -H 'content-type: application/json' \
  -d '{"prompt":"A desk organizer with three compartments, 120 mm wide, 80 mm deep, 42 mm high, 3 mm wall."}'
~~~

Set `include_steps: true` to persist bounded intermediate snapshots (base solid, cavity, dividers/cuts, and final export) for the process panel.

The response contains validated STEP and STL download URLs plus optional 3MF and GLB preview URLs. It also returns B-Rep/OCCT checks, geometry metrics, export round-trip status, a nominal manufacturing analysis, provenance, and Semantic CAD IR. Input units support `mm`, `cm`, `m`, and `in`; canonical geometry is always millimetres. Set `ARTIFACT_ROOT` to persistent storage in production.

## API surface

- `GET /health` reports CadQuery/OCCT, preview, LLM, authentication, and queue status. It does not require the API key.
- `GET /v1/process-profiles` returns FDM, SLA, CNC, and injection molding constraints.
- `POST /v1/models` synchronously generates a model. The optional `mode` is `standard` or `advanced`; `generation_strategy` accepts `legacy`, `ir`, or `auto`. The default and frontend path is `ir`, which runs LLM/primitive planning → generic Semantic CAD IR v0.2 → CadQuery/OCCT. `legacy` is an explicit compatibility mode; `auto` is only for controlled migrations and records any fallback reason. `strict_dimensions: true` rejects ambiguous unlabeled dimensions instead of applying defaults. Injection requests may pass `mold_pull_direction: [x, y, z]`; the vector is normalized for face-level draft checks and defaults safely to +Z.
- `POST /v1/jobs` creates a bounded asynchronous job; `GET /v1/jobs/{job_id}` polls it and `DELETE /v1/jobs/{job_id}` cancels it. A full queue returns HTTP 429. Generation mutations also use a bounded per-client rate limit (configurable with `RATE_LIMIT_WINDOW_SECONDS` and `MAX_MUTATIONS_PER_WINDOW`). Job responses include `progress.stage`, `progress.current_step`, elapsed time, and ordered `events`; the trace is updated after each real CAD operation rather than simulated on the client.
- `GET /v1/models/{model_id}/manifest` returns parameters, checks, process metadata, exports, and the reproducible manifest. In `auto`/`ir` generation, constraint repair attempts and fallback reasons are included in the manifest provenance and generation trace; `ir_fallback_code` is a stable category such as `llm_invalid_ir`, `unsupported_operation`, or `kernel_validation`.
- `GET /v1/models/{model_id}/ir` returns the v0.2 Semantic CAD IR used by the generation path. The IR is family-independent: primitives, features, constraints, selectors, and outputs are validated before kernel execution. Edge/face selectors support index, normal, position, area, parallel/perpendicular direction, and axis matching; IR execution trace records selector match indices/counts for audit and preview fallback highlighting.
- `POST /v1/ir/compile` accepts the same generic IR plus an optional `reference_ir` and `clearance_target_mm`; when CadQuery exposes a B-Rep distance, the response reports the measured mating clearance and method. Without a reference entity it remains `unknown`.
- `GET /v1/models/{model_id}/analysis` returns nominal wall-map samples, face-level DFM samples, issues, selector match metadata, and review status. Model checks also include measured/expected bounding boxes, per-axis dimension deltas, process tolerance, and `dimension_match`; face sampling remains conservative. Wall thickness uses B-Rep face distance when available and records the measured face pair/method; injection draft compares side-face normals against the configured pull direction; clearance stays `unknown` until mating geometry is supplied. When GLB face export succeeds, `glb_face_mapping` maps final OCCT face indices to `occt_face_<index>` nodes used by the viewer; selector face highlighting is enabled only after final-topology identity verification.
- `GET /v1/models/{model_id}/download?format=step|stl|3mf|glb` downloads an artifact.
- `GET /v1/models/{model_id}/steps/{step_id}` serves an intermediate GLB when `include_steps: true`; the final response and manifest expose `generation_trace`.

When `BACKEND_API_KEY` is set, every `/v1/*` request requires `X-API-Key`; `/health` remains public for readiness checks. CORS is not authentication. The in-memory cache and job queue are process-local, so run the container with one worker unless you replace them with shared storage/queue infrastructure.

## DeepSeek / OpenAI-compatible LLM

The generic IR planner is provider-neutral; advanced UI settings only change the amount of design context shown to the user. For local Docker testing with DeepSeek, copy the template and set:

~~~bash
cp .env.example .env
~~~

~~~env
BACKEND_API_KEY=replace-with-a-long-random-secret
LLM_API_KEY=your_deepseek_key
LLM_API_URL=https://api.deepseek.com/chat/completions
LLM_MODEL=deepseek-chat
~~~

The backend keeps both keys server-side, sends only the natural-language intent to the LLM, and validates the returned JSON before any geometry operation. Providers that reject `response_format=json_object` receive one compatibility retry without that field. Missing keys or provider failures use the deterministic primitive planner only when the prompt explicitly names a registered primitive; free-form descriptions fail clearly and never fall back to a model-family template.

The parser includes an L-bracket family (`angle`) for prompts such as `20x20 L-shaped profile, plate thickness 3`; the deterministic baseline wins when an advanced LLM proposes an unrelated family. The generated revision includes Semantic CAD IR in `manifest.json` and exposes it at `GET /v1/models/{model_id}/ir`. Manufacturing analysis is nominal: `review_required` stays true and `manufacturing_ready` stays false until face-level measurement is available. Export manifests record geometry metrics, checksums, axis/unit metadata, and STEP/mesh validation.

## Quality regression tests

Run the parser and IR contract tests without the CAD kernel:

~~~bash
pip install pytest fastapi pydantic
pytest -q test_quality.py
~~~

The Docker image should additionally be used for CadQuery/OCCT export smoke tests. The strict quality gate checks OCCT validity, non-zero faces, single-solid topology, STEP re-import metrics, and mesh watertightness when the optional mesh stack is available.


## P7 multi-output and assembly clearance

The v0.2 executor now preserves every node listed in outputs. POST /v1/ir/compile remains backward compatible (shape, output_node, metrics) and additionally returns output_nodes and output_metrics for all semantic entities. A mating reference_ir exposes reference_output_metrics and classifies measured distance as pass, warning, contact, or interference with the process tolerance.

Face DFM output includes wall_thickness_analysis. It records whether the result came from an OCCT B-Rep face distance or an opposing-face center proxy, with confidence and an explicit normal_ray_sampling capability flag. Consumers should treat proxy output as conservative until a kernel-backed ray sample is available.

The backend now attempts an optional OCCT normal-ray thickness sample from each face center. Capability is exposed as occt_normal_ray_available on /health; unavailable kernels retain the explicit proxy result and never label it as ray-sampled.

All declared semantic outputs are now checked individually for valid B-Rep, positive volume, non-zero faces, and single-solid topology. The compiler rejects the request with per-entity output_quality details if any output fails.

When an IR declares multiple outputs and the mesh stack is available, generation also emits model_entities.glb (download format glb_entities). Its nodes are named output_<node>_occt_face_<index>, with analysis.glb_output_mapping preserving the semantic entity mapping.


## CadQuery/OCCT 镜像回归

Dockerfile 使用 CadQuery 2.4.0，并安装 VTK/OCCT 在 slim Linux 中所需的无桌面运行库。它会复制 backend 下全部 Python 模块，而不是只复制入口文件。构建后可运行：

~~~bash
docker build -t texttocad-backend ./backend
docker run --rm texttocad-backend python kernel_smoke.py
~~~

kernel_smoke.py 会实际构造薄壁凹腔，执行面级 DFM/法向射线能力检查，并验证两个独立 Semantic CAD IR 输出都通过 B-Rep 质量门。相同检查由 GitHub Actions 的 kernel-smoke job 自动执行。


## IR-first product contract

The production path is now `natural language -> Semantic CAD IR -> static validation -> constraint solve/repair -> CadQuery/OCCT -> B-Rep/DFM verification`. The frontend always requests `generation_strategy: "ir"`. The IR contains primitives, features, datums, parameters, constraints, and outputs; it does not contain a required model-family enum. `ModelParameters.kind` remains only as a response compatibility field.

The IR executor (`ir_executor.py`) provides full support for:
- Primitives: `box`, `cylinder`, `sphere`, `cone`, `torus` (`Solid.makeTorus`), `regular_polygon`, `polygon_prism`, `sketch`.
- Spatial transformations: inline `position`/`origin`/`center` parameter translation, `translate`, `rotate`, `mirror`.
- CSG Booleans: `union`, `cut`, `intersect` with multi-node topological inputs.
- Feature finishing: `fillet`, `chamfer`, `shell`, `linear_pattern`, `polar_pattern`.

When no LLM key is configured, the backend compiles explicit primitive and boolean hole prompts (box/cube, sphere, cylinder, cone, torus, regular polygons, and hollow/through-hole geometry) with the deterministic primitive planner. A free-form description without an LLM returns a clear 503 explaining how to configure the provider. This prevents a missing provider from producing a misleading default model.
