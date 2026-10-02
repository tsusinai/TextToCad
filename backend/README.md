# TextToCad geometry backend

This service turns a natural-language part description into a validated parametric B-Rep with CadQuery/OCCT. It is intentionally deterministic at the geometry boundary: an LLM or a richer parser can be added before the `parse_prompt` contract without changing the export and validation pipeline.

## Run locally

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8787
```

The API is available at `http://localhost:8787`.

```bash
curl -X POST http://localhost:8787/v1/models \
  -H 'content-type: application/json' \
  -d '{"prompt":"A desk organizer with three compartments, 120 mm wide, 80 mm deep, 42 mm high, 3 mm wall."}'
```

The response contains validated STEP and STL download URLs plus optional 3MF and GLB preview URLs. It also returns `checks` for B-Rep validity, topology, volume, wall thickness, edge treatment, overhang, draft, clearance, and export readiness. The manifest records the selected process profile, millimetre units, tolerances, wall-map samples, issue list, STEP schema, and generator version. Set `ARTIFACT_ROOT` to persistent storage in production and set `CORS_ORIGINS` to the deployed frontend origin.

## API surface

- `GET /health` reports CadQuery/OCCT availability and available process profiles.
- `GET /v1/process-profiles` returns FDM, SLA, CNC, and injection molding constraints.
- `POST /v1/models` accepts `prompt`, `units`, and `process`, then builds a solid, validates the B-Rep and process checks, and writes STEP/STL artifacts.
- `GET /v1/models/{model_id}/manifest` returns parameters, validation checks, process metadata, and the reproducible manifest.
- `GET /v1/models/{model_id}/analysis` returns wall-map samples and localized manufacturing issues.
- `GET /v1/models/{model_id}/download?format=step|stl` downloads a manufacturing artifact.

The current parser supports English and Chinese dimensions, footprints, compartment counts, wall/bottom thickness, and chamfer/radius values. STEP export attempts AP242 and records the actual schema used; preview meshes are converted to 3MF and GLB when the optional mesh dependencies are available. For production text understanding, replace or extend `parse_prompt` with an LLM structured-output adapter that returns the same `ModelParameters` fields, then retain the deterministic geometry and validation stages.

## DeepSeek / OpenAI-compatible LLM

Advanced mode is provider-neutral. For local Docker testing with DeepSeek, copy the template and set:

    cp .env.example .env
    LLM_API_KEY=your_deepseek_key
    LLM_API_URL=https://api.deepseek.com/chat/completions
    LLM_MODEL=deepseek-chat

The backend keeps the key server-side, sends only the natural-language intent, and validates the returned JSON before any geometry operation. Providers that reject response_format=json_object receive one compatibility retry without that field. Missing keys or provider failures fall back to the deterministic parser.

The generated revision includes Semantic CAD IR in manifest.json and exposes it at GET /v1/models/{model_id}/ir.
