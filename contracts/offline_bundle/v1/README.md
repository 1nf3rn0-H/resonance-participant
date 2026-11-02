# Resonance offline contract 1.0.0 — M0

The single authoritative, portable contract for the future participant app and this private admin app. See [PROTOCOL.md](PROTOCOL.md) (DRAFT, not preregistered), [questions.json](questions.json), [sampling.json](sampling.json), and [schemas](schemas/). Do not independently edit vendored copies. New behavior requires a new release/version and compatibility fixtures.

## What is executable

- `schemas/bundle.schema.json`: complete logical bundle, strict fields, portable JSON Schema 2020-12.
- `schemas/records.schema.json`: reusable `$defs` for each JSONL record type; `manifest.schema.json` for the manifest.
- `validate.py`: normative shared cross-record/consent/hash/state/sampling validator. Both apps vendor this same implementation. JSON Schema alone cannot enforce transaction/foreign-reference invariants.
- `sampling.py`: common historical universe, native mapping and collection-slot draw reference. It does not implement or modify either native surfacer.
- `canonical.py` / `canonical.mjs`: independent Python/JavaScript JCS+SHA-256 and scientific identity implementations.
- `schema.mjs`: JS schema checks for structured producer data; raw untrusted JSON must use the shared strict parser/validator, not plain JSON.parse alone.
- `archive.py`: bounded, allowlisted ZIP/JSONL codec with checksums; no extraction/execution.
- `crypto.py`: age v1 X25519 encrypted export/import; preview, explicit grants and recipient pin required.
- `fixtures/catalog.json`: expected valid/invalid/hostile outcomes. `PUBLIC_TEST_KEYS.json` is intentionally public and synthetic; never use its key for a study.
- `study-config.template.json`: intentionally UNCONFIGURED, export disabled. Real recipient, enrollment seed precommitment, authenticated release and real consent approval are M1/deployment requirements.

The package has no dependency on `api/`, private prompts, research database credentials or network services. Python dependencies are pinned in `requirements.txt`; JavaScript dependencies in `package.json`. Install/vendor them at build time, never during a study session. No actual private research identity is included.

## Hash domains

The canonicalization standard is [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html), including UTF-16 property sorting, ECMAScript IEEE-754 formatting, no Unicode normalization, lone-surrogate/non-finite rejection and preserved array order. Parsed JSON rejects duplicate object keys. Count/ordinal fields are safe bounded integers; non-identifier floating values follow IEEE-754. Larger exact identifiers must be strings.

1. `record_hash`: JCS/SHA-256 of the record excluding ONLY its top-level `record_hash`. Includes original source ID and exact audit clocks.
2. `manifest.integrity_hash`: JCS/SHA-256 of the entire logical bundle excluding ONLY `manifest.integrity_hash`; includes `content_hash`, preview/authorization and all source records.
3. `manifest.content_hash`: scientific identity projection v1, implemented in `scientific_hash`/`scientificHash`. Excludes `record_id`, `record_hash`, `created_at`, `generated_at`, `actual_imported_at`, `received_at`. Known reference fields resolve to parent semantic keys in the documented SECTION_ORDER. Top-level record sets sort by canonical UTF-8 content; ordered memberships/questions/answers remain ordered. Keep historical/availability/cutoff/collection/decision/response clocks, versions, source-data status, native results, questions, parameters and seed. Source availability changes are scientifically meaningful and are not discarded. Changing a bundle UUID or export creation time changes exact integrity but not scientific identity.
4. ZIP `checksums.json`: byte SHA-256 per file, excluding the checksum file itself. It detects altered file encodings as well as logical changes. Reordering ZIP entries does not alter the logical bundle identity.

Research database keys never replace source IDs in captured records. Preserve both exact integrity and scientific identity. Neither is proof of sender identity or of untampered local capture before export.

## Archive layout

After age decryption, allowed files are:

```text
manifest.json
consent/record.json
provenance/input_manifest.json
export/preview.json
export/authorization.json
sampling/episode_snapshots.jsonl
sampling/eligible_windows.jsonl
sampling/native_candidates.jsonl
sampling/mappings.jsonl
sampling/assignments.jsonl
prompts/prompt_packets.jsonl
prompts/prompt_events.jsonl
prompts/submissions.jsonl
prompts/locks.jsonl
checksums.json
ingestion/imports.jsonl   # HISTORY_AND_RESPONSES only
ingestion/tracks.jsonl    # HISTORY_AND_RESPONSES only
ingestion/events.jsonl    # HISTORY_AND_RESPONSES only
```

This freezes concrete logical records and the JSONL mapping from the handoff; it does not exchange SQLite dumps or executables. Response-only logical bundles have empty history arrays and must omit those ZIP entries. All remaining listed files are required, even if their JSONL arrays are empty. No arbitrary extra files or convenience CSV in 1.0.0. UTC exchange clocks use exactly millisecond precision; the raw provider timestamp remains separate and unchanged. Device wall clocks are explicitly unverified. Archive cap 16 MiB, expanded total 32 MiB, per-file 8 MiB, JSONL line 1 MiB, at most 100k lines/file, 250k total records, 500k membership references; compression ratio capped at 200. Symlinks, traversal, encrypted ZIPs and duplicate paths are rejected. age is the outer encryption layer.

## Use and compatibility

```sh
python3 -m contracts.offline_bundle.v1.cli validate < capture.json
python3 -m contracts.offline_bundle.v1.cli archive < synthetic-fixture.zip
npm run test:contracts
python3 -m scripts.export_offline_contract --output /tmp/resonance-offline-contract-1.0.0.zip
```

`seal()` is a producer/test utility, never an importer repair operation. The importer validates supplied hashes and preserves captured values. Identical submission IDs/content are reused, and different content under the same identity conflicts. Unknown contract versions fail closed; no silent migration adapter exists at M0. Existing legacy archives remain on their separate existing path.

`RELEASE.json` commits to every runtime/spec/schema/config/fixture/vector artifact. The export command verifies it before creating a deterministic vendoring archive. Future participant CI must run the same fixtures and pin the same release digest. This package remains inside the private repo until the participant repo is explicitly created; no repository/publication action is part of M0.
