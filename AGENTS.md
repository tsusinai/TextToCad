# AGENTS.md

## Overview & Architecture

- **Stack**: Single-file static frontend (`index.html`) + Python FastAPI CadQuery/OCCT geometry backend (`backend/`).
- **No Node.js/npm**: Frontend has no `package.json`, build step, or bundler; it loads Three.js 0.161.0 via ESM importmap CDN. Do not create `package.json` or add npm dependencies.
- **Two-Layer CAD Pipeline**: The LLM never writes or executes Python/CadQuery code directly. The LLM only plans or patches **Semantic CAD IR v0.2** (`docs/SEMANTIC_CAD_IR.md`). CadQuery/OCCT executes the IR deterministically.
- **Deterministic Fallback**: If LLM API keys are unset or the provider fails, explicit primitive and CSG prompts fall back to local rule-based parsing. Unconfigured free-form prompts return HTTP 503 instead of falling back to legacy templates.
- **Single-Worker Constraint**: Generation job queues (`MAX_CONCURRENT_JOBS`) and task state in `backend/app.py` are process-local. Uvicorn/Docker must run with `--workers 1`.

## Environment & Python Gotchas

- **Python Version**: CadQuery 2.4.0, OCCT bindings, and `nptyping` require **Python 3.11** and `numpy<2`. Do not run backend tasks with system Python 3.12+ (e.g., host Python 3.14).
- **Windows Virtualenv**: The local environment is at `backend\.venv`. Always execute Python tools using `backend\.venv\Scripts\python.exe` or `backend\.venv\Scripts\pytest.exe`.
- **Configuration & Secrets**: Backend config is loaded from `backend/.env` (template at `backend/.env.example`).
  - Key variables: `LLM_API_KEY`, `LLM_API_URL` (default DeepSeek), `LLM_MODEL`.
  - When `BACKEND_API_KEY` is set, all `/v1/*` endpoints require the `X-API-Key` header (`/health` remains unauthenticated).

## Developer Commands

### Backend Server
- **Windows (local venv)**:
  ```powershell
  backend\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8787 --env-file backend/.env --reload
  # Alternatively: start_backend.bat
  ```
- **Docker Compose**:
  ```bash
  docker compose up --build -d
  # Health check: curl http://localhost:8787/health
  ```

### Frontend Server
- **Local static server**:
  ```powershell
  backend\.venv\Scripts\python.exe -m http.server 8000
  # Alternatively: start_frontend.bat (port 8000)
  # Access UI: http://localhost:8000/?backend=http://localhost:8787
  ```
- **Batch Launcher**: `start_all.bat` starts both backend (port 8787) and frontend (port 8000).

### Verification & Tests
- **Fast contract tests (CI equivalent, mock-friendly, no CAD kernel needed)**:
  ```powershell
  backend\.venv\Scripts\pytest.exe -q backend/test_quality.py
  ```
- **Geometry kernel smoke check (validates CadQuery/OCCT B-Rep & ray DFM)**:
  ```powershell
  backend\.venv\Scripts\python.exe backend/kernel_smoke.py
  ```
- **In-container smoke check (mirrors CI `kernel-smoke` job)**:
  ```bash
  docker build -t texttocad-backend:kernel-smoke ./backend
  docker run --rm texttocad-backend:kernel-smoke python kernel_smoke.py
  ```
- **Agent and contract test suites**:
  ```powershell
  backend\.venv\Scripts\pytest.exe -q backend/test_agent_retrieval_and_contracts.py backend/test_agent_simulation.py backend/test_assembly_repair.py backend/test_canonical_scale_and_assembly.py backend/test_multigate_inspector.py backend/test_multiview_annotations.py
  ```

## Modeling & Implementation Quirks

- **Mount Overlap**: In `backend/ir_executor.py`, non-cutter face mounting applies an intentional `0.05mm` default overlap (`1.5mm` for cylinders/extrusions on X/Y faces) to avoid non-manifold coincident coplanar faces during OCCT boolean union. Bounding box calculations on mounted assemblies must account for this tolerance.
- **Canonical Units**: The canonical internal unit is always millimeters (`mm`). Prompts specifying `cm`, `m`, or `in` are converted to mm before IR compilation; provenance tracks raw user inputs.
- **Intermediate Artifacts**: Setting `include_steps: true` in generation requests saves intermediate step GLB snapshots for the UI timeline. Output artifacts are saved to `ARTIFACT_ROOT` (`backend/artifacts/` by default).
