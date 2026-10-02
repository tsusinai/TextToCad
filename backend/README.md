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

The response contains validated STEP and STL download URLs plus `checks` for B-Rep validity, topology, volume, wall thickness, edge treatment, overhang, draft, clearance, and export readiness. The manifest records the selected process profile, millimetre units, tolerances, and generator version. Set `ARTIFACT_ROOT` to persistent storage in production and set `CORS_ORIGINS` to the deployed frontend origin.

## API surface

- `GET /health` reports CadQuery/OCCT availability and available process profiles.
- `GET /v1/process-profiles` returns FDM, SLA, CNC, and injection molding constraints.
- `POST /v1/models` accepts `prompt`, `units`, and `process`, then builds a solid, validates the B-Rep and process checks, and writes STEP/STL artifacts.
- `GET /v1/models/{model_id}/manifest` returns parameters and validation checks.
- `GET /v1/models/{model_id}/download?format=step|stl` downloads a manufacturing artifact.

The current parser supports English and Chinese dimensions, footprints, compartment counts, wall/bottom thickness, and chamfer/radius values. For production text understanding, replace or extend `parse_prompt` with an LLM structured-output adapter that returns the same `ModelParameters` fields, then retain the deterministic geometry and validation stages.
