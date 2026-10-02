# TextToCad

Natural-language to CAD workspace with a front-design interface and a CadQuery geometry backend.

## What is included

- Natural-language prompt parsing with English and Chinese dimensions.
- Browser preview with generated isometric, top, and front projections.
- Optional backend connection for validated OCCT B-Rep geometry.
- STEP and STL artifact generation from the backend; local OBJ fallback in the static demo.
- Responsive static front end with no build step.

## Geometry backend

The production path lives in backend:

1. POST /v1/models parses a prompt into bounded millimetre parameters.
2. CadQuery/OCCT builds a tray, organizer, cable clip, or solid.
3. B-Rep validity, single-solid, volume, and bounding-box checks run before export.
4. Validated STEP and STL artifacts are written to persistent storage and exposed by download URLs.

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
