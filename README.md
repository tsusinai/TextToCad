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

Open index.html directly or serve the repository with any static server. Without a backend URL, the browser keeps a deterministic preview and OBJ export so the interface remains usable.

## Live version

GitHub Pages is published from the gh-pages branch:
https://tsusinai.github.io/TextToCad/

## Product plan

The phased roadmap and Phase 1 acceptance criteria are in [PLAN.md](PLAN.md).


The current backend includes manufacturing profiles, nominal wall-map analysis, localized issue reporting, reproducible export manifests, async job status, and editable parameter regeneration from the UI.
