# TextToCad

Natural-language to CAD workspace with a front-design interface and a CadQuery geometry backend.

## What is included

- Natural-language prompt parsing with English and Chinese dimensions, including tray, organizer, cable clip, plant pot, lamp base, and pen cup families.
- Browser preview with generated isometric, top, and front projections, plus drag orbit, Shift-drag pan, wheel zoom, FIT reset, and touch pointer controls.
- Optional backend connection for validated OCCT B-Rep geometry.
- STEP and STL artifact generation from the backend, with optional 3MF/GLB previews; local OBJ fallback in the static demo. GLB artifacts open in a progressive OrbitControls viewer when the browser can load Three.js.
- Responsive static front end with no build step.

## Geometry backend

The production path lives in backend:

1. POST /v1/models parses a prompt into bounded millimetre parameters; production clients can use POST /v1/jobs with GET/DELETE status control for cancellable generation.
2. CadQuery/OCCT builds a tray, organizer, cable clip, plant pot, lamp base, pen cup, or solid.
3. B-Rep validity, single-solid, volume, and bounding-box checks run before export.
4. Validated STEP and STL artifacts are written to persistent storage and exposed by download URLs; manifest files are persisted for reproducibility, with TTL cleanup and repeat-prompt caching.

Run it locally:

    cd backend
    python -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    uvicorn app:app --reload --port 8787

To connect the static UI, open the page with a backend query parameter:

    https://tsusinai.github.io/TextToCad/?backend=http://localhost:8787

A deployed frontend can instead define window.FORM_CAD_BACKEND_URL before the inline application script. Configure CORS_ORIGINS and a persistent ARTIFACT_ROOT for production.

## Local preview

Open index.html directly or serve the repository with any static server. Without a backend URL, the browser keeps a deterministic SVG concept preview and OBJ export so the interface remains usable; the page labels this as a concept preview because a true GLB/OCCT solid requires the backend.

## Live version

GitHub Pages is published from the gh-pages branch:
https://tsusinai.github.io/TextToCad/

## Product plan

The phased roadmap and Phase 1 acceptance criteria are in [PLAN.md](PLAN.md).


The current backend includes manufacturing profiles, nominal wall-map analysis, localized issue reporting, reproducible export manifests, async job status, and editable parameter regeneration from the UI.

## LLM advanced mode

The default **Standard** mode uses the deterministic parser and does not require an API. **Advanced · LLM** mode sends the user's natural-language intent plus a deterministic baseline to an OpenAI-compatible chat-completions endpoint. The model is asked for a small JSON parameter object; the backend clamps every dimension, validates feature flags, builds the solid with CadQuery/OCCT, and runs the existing B-Rep checks before returning any artifact.

Configure the provider only on the backend:

    LLM_API_KEY=...
    LLM_API_URL=https://api.openai.com/v1/chat/completions
    LLM_MODEL=gpt-4o-mini
    LLM_TIMEOUT_SECONDS=20
    LLM_MAX_RESPONSE_BYTES=65536

The browser never receives the key. If the key is missing, the provider times out, or the response is invalid, Advanced mode falls back to the deterministic baseline and returns the reason in "assumptions"; it never executes model-produced CAD code. Set "mode" to "advanced" in either POST /v1/models or POST /v1/jobs to opt in:

    {"prompt":"一个带排水孔的极简花盆，直径 90 毫米，高 82 毫米","units":"mm","process":"fdm","mode":"advanced"}

The response and manifest.json record "mode", "llm_used", and bounded assumptions so a revision can be audited and reproduced. The generated geometry still comes exclusively from the supported parametric builders. Each revision also stores a Semantic CAD IR in its manifest and exposes it at GET /v1/models/{id}/ir, making intent, parameter provenance, feature planning, and constraints auditable.

## Why this architecture is used

Text-to-CAD is split into an intent layer and a geometry layer:

1. Natural language is interpreted into a bounded CAD specification.
2. The specification becomes a parametric feature tree.
3. CadQuery/OCCT performs the solid operations and B-Rep validation.
4. STEP/STL/3MF/GLB artifacts are exported and the browser previews the result.

An LLM is therefore a design-intent planner, not an unchecked CAD-code executor. This keeps manufacturing rules, units, topology checks, and reproducible exports inside the backend.

A stronger future implementation can add a versioned JSON Schema or Pydantic model for the intent contract, a feature-grammar retrieval layer for uncommon parts, a constraint solver that explains and repairs conflicts, and a second geometry-review pass that measures actual faces instead of relying on nominal wall estimates. For manufacturable products, this constrained hybrid approach is a better default than direct text-to-mesh generation; direct mesh or B-Rep generation can be added later as an exploratory mode with separate validation and export gates.


