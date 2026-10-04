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
- `POST /v1/models` synchronously generates a model. The optional `mode` is `standard` or `advanced`; `generation_strategy` accepts `legacy`, `ir`, or `auto`. Standard mode defaults to the deterministic builder; advanced UI requests `auto`, which tries LLM → generic Semantic CAD IR v0.2 → CadQuery/OCCT and falls back to the deterministic builder with a recorded reason. `strict_dimensions: true` rejects ambiguous unlabeled dimensions instead of applying defaults.
- `POST /v1/jobs` creates a bounded asynchronous job; `GET /v1/jobs/{job_id}` polls it and `DELETE /v1/jobs/{job_id}` cancels it. A full queue returns HTTP 429. Generation mutations also use a bounded per-client rate limit (configurable with `RATE_LIMIT_WINDOW_SECONDS` and `MAX_MUTATIONS_PER_WINDOW`). Job responses include `progress.stage`, `progress.current_step`, elapsed time, and ordered `events`; the trace is updated after each real CAD operation rather than simulated on the client.
- `GET /v1/models/{model_id}/manifest` returns parameters, checks, process metadata, exports, and the reproducible manifest. In `auto`/`ir` generation, constraint repair attempts and fallback reasons are included in the manifest provenance and generation trace.
- `GET /v1/models/{model_id}/ir` returns the v0.2 Semantic CAD IR used by the generation path. The IR is family-independent: primitives, features, constraints, selectors, and outputs are validated before kernel execution.
- `GET /v1/models/{model_id}/analysis` returns nominal wall-map samples, issues, and review status.
- `GET /v1/models/{model_id}/download?format=step|stl|3mf|glb` downloads an artifact.
- `GET /v1/models/{model_id}/steps/{step_id}` serves an intermediate GLB when `include_steps: true`; the final response and manifest expose `generation_trace`.

When `BACKEND_API_KEY` is set, every `/v1/*` request requires `X-API-Key`; `/health` remains public for readiness checks. CORS is not authentication. The in-memory cache and job queue are process-local, so run the container with one worker unless you replace them with shared storage/queue infrastructure.

## DeepSeek / OpenAI-compatible LLM

Advanced mode is provider-neutral. For local Docker testing with DeepSeek, copy the template and set:

~~~bash
cp .env.example .env
~~~

~~~env
BACKEND_API_KEY=replace-with-a-long-random-secret
LLM_API_KEY=your_deepseek_key
LLM_API_URL=https://api.deepseek.com/chat/completions
LLM_MODEL=deepseek-chat
~~~

The backend keeps both keys server-side, sends only the natural-language intent to the LLM, and validates the returned JSON before any geometry operation. Providers that reject `response_format=json_object` receive one compatibility retry without that field. Missing keys or provider failures fall back to the deterministic parser.

The parser includes an L-bracket family (`angle`) for prompts such as `20x20 L-shaped profile, plate thickness 3`; the deterministic baseline wins when an advanced LLM proposes an unrelated family. The generated revision includes Semantic CAD IR in `manifest.json` and exposes it at `GET /v1/models/{model_id}/ir`. Manufacturing analysis is nominal: `review_required` stays true and `manufacturing_ready` stays false until face-level measurement is available. Export manifests record geometry metrics, checksums, axis/unit metadata, and STEP/mesh validation.

## Quality regression tests

Run the parser and IR contract tests without the CAD kernel:

~~~bash
pip install pytest fastapi pydantic
pytest -q test_quality.py
~~~

The Docker image should additionally be used for CadQuery/OCCT export smoke tests. The strict quality gate checks OCCT validity, non-zero faces, single-solid topology, STEP re-import metrics, and mesh watertightness when the optional mesh stack is available.
