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

The response contains validated STEP and STL download URLs plus optional 3MF and GLB preview URLs. It also returns B-Rep checks, a nominal manufacturing analysis, provenance, and Semantic CAD IR. Set `ARTIFACT_ROOT` to persistent storage in production.

## API surface

- `GET /health` reports CadQuery/OCCT, preview, LLM, authentication, and queue status. It does not require the API key.
- `GET /v1/process-profiles` returns FDM, SLA, CNC, and injection molding constraints.
- `POST /v1/models` synchronously generates a model. The optional `mode` is `standard` or `advanced`.
- `POST /v1/jobs` creates a bounded asynchronous job; `GET /v1/jobs/{job_id}` polls it and `DELETE /v1/jobs/{job_id}` cancels it. A full queue returns HTTP 429.
- `GET /v1/models/{model_id}/manifest` returns parameters, checks, process metadata, exports, and the reproducible manifest.
- `GET /v1/models/{model_id}/ir` returns Semantic CAD IR v0.1.
- `GET /v1/models/{model_id}/analysis` returns nominal wall-map samples, issues, and review status.
- `GET /v1/models/{model_id}/download?format=step|stl|3mf|glb` downloads an artifact.

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

The generated revision includes Semantic CAD IR in `manifest.json` and exposes it at `GET /v1/models/{model_id}/ir`. Manufacturing analysis is nominal: `review_required` stays true for warnings and errors, and face-level measurement remains a future enhancement.
