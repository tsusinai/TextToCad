# TextToCad phased product plan

This plan moves TextToCad from a prompt demo to a trustworthy, manufacturable CAD workspace. The first phase is deliberately narrow: a user should understand what the system interpreted, see whether the result passed checks, and recover an earlier revision.

## Phase 1 — Trustworthy generation loop

Status: implementing in this release.

Deliverables:

- Interpretation preview with dimensions, compartments, edge treatment, units, and explicit default assumptions.
- Generation state that distinguishes local preview from a backend OCCT B-Rep result.
- Dynamic manufacturing checks driven by backend validation when available and by conservative local checks offline.
- Local revision history with prompt, interpreted parameters, source, timestamp, restore, and clear actions.
- Graceful backend failure: the preview remains usable and the UI explains that STEP/STL requires a connected backend.

Acceptance criteria:

- A user can inspect the interpreted specification before generating.
- A generated revision can be restored after another prompt is used.
- The readiness panel updates after every generation and does not show stale results.
- A backend response with failed checks is visible as a warning instead of being presented as fully ready.
- The same behavior works in English and Chinese.

## Phase 2 — Conversational parametric editing

Status: completed in this release.

Delivered:

- Follow-up instructions for relative and absolute width, depth, height, wall, chamfer, and compartment edits.
- Canonical prompt generation so edited browser specs can be sent to the geometry backend.
- A feature tree showing the base solid, shell, compartments, and edge treatment.
- Revision diffs showing changed parameters and one-click restoration of an exact canonical revision.
- Three consecutive edits can be made without rewriting the original design prompt.

Acceptance target: a user can make three consecutive edits without rewriting the original prompt.

## Phase 3 — Manufacturing-grade CAD

Status: completed in this release.

Delivered:

- FDM, SLA, CNC, and injection molding process profiles in the frontend and backend.
- Process-aware wall thickness, edge treatment, overhang, draft, clearance, and export checks.
- Wall-map samples and localized issue markers in the manufacturing panel.
- Reproducible STEP/STL manifests containing units, process profile, parameters, checks, analysis, and generator version.
- AP242 STEP export attempt with an explicit fallback schema recorded in the manifest.
- Optional 3MF and GLB preview artifacts with download endpoints.
- Backend endpoint for retrieving process profiles and per-model analysis.

Follow-up work for the next CAD kernel iteration:

- Replace parametric wall samples with face-level thickness maps.
- Add true draft angles, machining access, support-aware orientation, and process-specific feature generation.
- Expand AP242 product metadata and preview materials.

Acceptance target: every exported model includes units, parameters, checks, and a reproducible generation manifest.

## Phase 4 — Collaboration and scale

Add shareable project links, persistent storage, background job queues, signed artifact URLs, rate limits, usage telemetry, and team permissions.

Acceptance target: long-running jobs survive page refreshes and artifacts remain downloadable from a project revision.

## Product guardrails

- Never hide a default assumption; show it beside the interpreted values.
- Never report a manufacturing check as passed unless the current revision was checked.
- Keep geometry deterministic and versioned at the backend boundary.
- Keep Chinese and English flows feature-equivalent.

## Measurement

Track interpretation confirmation rate, valid-B-Rep rate, median generation time, backend failure rate, revision restore rate, export success rate, and manufacturing check failures by process profile.
