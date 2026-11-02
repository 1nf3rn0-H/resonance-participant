# Provenance and acceptance

M1 is a separate repository with a clean history. The frozen M0 package is copied from the verified release, not from private Git history. Source allowlist: the contract package, `src/data.ts` as `participant/samplers/v03.ts`, and pure `api/ped.py` as `participant/samplers/ped.py`. Their SHA-256 values match the vendored `native-surfacer-pins.json`; a standalone helper supplies only timestamp normalization. The v0.3 type-only imports are removed at execution by Node's built-in type stripping, so no research type/ontology file is needed.

## M0 clean-checkout gate

Before app implementation, the frozen export was committed into a new minimal Git repository and cloned into a separate checkout. A fresh virtual environment without system packages installed only the contract's pinned requirements; JavaScript used a fresh `npm ci` from the vendored lockfile. Python was run with `-I`, excluding development PYTHONPATH/user-site state. Python passed all 25 fixture cases and canonical vectors; JavaScript passed the schema/hash/producer cases. The release digest was exactly:

`2c7db223667618d3c9f935ca55a76c62cd4171d93987ee6b59f422768f9fa574`

The app's CI repeats that shared contract selftest from its own clean GitHub checkout. Runtime dependencies are installed at setup only. Neither application independently edits the contract.

## Runtime boundaries

- Standard-library local HTTP service, bundled HTML/CSS/JS, SQLite with foreign keys/WAL/FULL synchronization/private directory permissions.
- Loopback binding, host validation, per-launch HttpOnly/SameSite cookie and same-origin/token checks for writes. No cloud accounts, telemetry, remote fonts or schemas.
- One frozen imported input per study; native behavioral results cached once, all candidate/exclusion/mapping evidence retained.
- All collection slots use M0's seed-committed, UTC collection-day policy. No outcome-driven reseeding, duplicate slots or overlapping invitations.
- Atomic neutral capture, answer-set hash and unique lock; immutable records/runs/sessions/slots; separate follow-up capture; idempotent final saves.
- Only M0's two neutral questions can be displayed. The unchanged PED file includes its legacy packet helper, but its question strings/packets are never used by this app. M0 is the sole participant question bank.
- Native raw results stay local. Exports contain candidate provenance and, only for history-authorized scope, per-event forecast/model evidence. Responses-only packets retain music/time context for candidate windows but omit individual play logs and forecasts; source history is labeled independently unverifiable.
- Explicit preview/consent/recipient pin before age encryption; final wire archive is checked against M0's receiver limits; exported source values are not repaired or silently recomputed.

## Scope and limits

Retrospective pilot, not prospective EMA or a validated psychological model. No LLM investigator, audio/lyric analysis or psychological profiling. M2 researcher-side integration/review UI is separate. Installation prerequisites are Python 3.11+ and Node 22.18+; installer packaging and real-study enrollment/signing procedures can be improved after this first complete volunteer workflow. Windows launcher is included but not yet part of automated platform acceptance.

Tests use synthetic histories, including forbidden account/IP fields to prove allowlisting, and temporary test keys. Public fixture keys inside the contract are deliberately disclosed and must never be used for a study. No private operational researcher key or participant history belongs in this repository.
