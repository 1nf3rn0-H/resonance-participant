# Resonance Participant

A standalone, local application for a retrospective listening-history pilot. Import Spotify history, answer a listening reflection, and explicitly save an encrypted package for your researcher. The app never uploads data automatically and needs no internet during normal operation.

The research/admin engine, LLM investigator, audio analysis and psychological profiling are not included. This is a draft research instrument, not a diagnostic product.

## Install and start

Prerequisites: **Python 3.11+** and **Node.js 22.18+**. Node is used only to run the frozen v0.3 behavioral sampler; no npm packages or internet are needed to run it. Guided installation is appropriate for this first pilot.

```sh
git clone https://github.com/1nf3rn0-H/resonance-participant.git
cd resonance-participant
./install.sh
./start.sh
```

Installation downloads three pinned Python dependencies and verifies the frozen contract/sampler hashes. Once installation succeeds, disconnect from the internet: `./start.sh` only starts the local app and opens its loopback launch link. If installation has not been completed, the launcher explicitly runs that first-time setup. It does not install anything during subsequent sessions.

On Windows, install the same prerequisites and double-click `start.bat` (or run it from a terminal). The Windows launcher is provided; automated acceptance targets Linux and the core workflow is also tested on macOS.

The UI binds only to **127.0.0.1**. Leave the terminal open while using the app. Press Ctrl+C to close it, then run the launcher again to resume. The new launch link reconnects the browser; your study, drafts, locked answers and cached encrypted exports persist in SQLite.

Default data directory: `~/.local/share/resonance-participant`. To use a dedicated alternate directory/port:

```sh
./start.sh --data-dir /private/path/my-participant-study --port 8766
```

Use an empty dedicated directory for a new study. Do not commit local data, original history, enrollment configuration or exported packages to Git.

## One participant's workflow

1. Receive a **public study configuration** and its SHA-256 fingerprint from your researcher through the agreed trusted channel. The participant never needs a private decryption key.
2. Open the local app, select that configuration, verify its fingerprint, consent to local processing and choose whether normalized history may accompany an eventual export. Responses-only sharing includes episode song/time summaries and experimental selection evidence, including unasked candidate periods; it omits individual play records and per-event forecasts. The full export is shown before sharing. The choice is frozen for this local study.
3. Import a Spotify streaming-history JSON file, or a ZIP containing streaming-history JSON files. Extended and older `StreamingHistory` formats are supported. Original files, account names, IPs and device fields are not retained. Unknown skips remain unknown; reconstructed starts stay estimated.
4. Open today's reflection. The frozen Random/v0.3/PED policy assigns **one collection-day slot per UTC day**. Historical listening dates do not create extra daily slots. Native candidates and unselected common windows are retained for audit, while the interview hides arm/scores.
5. Answer recognition and event-specific meaningfulness, including explicit uncertainty/non-recall options. Save and lock your initial answers. Then optionally answer up to two separately versioned follow-ups. Locked answers cannot be edited; identical retries are idempotent.
6. Close/reopen at any point to resume saved progress. Drafts save on field changes. Use the explicit save/lock button before relying on a final response.
7. Consent to response sharing, inspect the full logical export, then confirm **Save encrypted package**. Download the `.resonance.age` file and transfer it yourself using the agreed method. Nothing is transmitted automatically.

This initial pilot accepts up to 10,000 plays per study, subject to M0's unchanged archive/audit size budgets. Larger histories can be limited with the import date-range controls. Oversized cohorts are rejected before interviewing; no history is silently truncated. The analysis scope is all frozen imported history; v0.3 weights and PED internals are unchanged.

## Study configuration

The researcher supplies a public recipient, study identifier, opaque participant alias and contact text. The public configuration is pinned by its RFC 8785/SHA-256 fingerprint. Obtain that fingerprint through the trusted study channel; a checksum alone is not identity authentication. The intentionally public M0 fixture key is rejected for participant configuration.

A coordinator can prepare the **public** file with this helper, which never creates or requests a private study key:

```sh
.venv/bin/python scripts/create_study_config.py \
  --study-id pilot-retro-2026 --participant-alias P-OPAQUEALIAS \
  --recipient age1RESEARCHER_PUBLIC_RECIPIENT \
  --contact 'Your agreed researcher contact' --output study.json
```

Pass only a real age X25519 public recipient. Send the file/fingerprint to the participant. Enrollment and consent approval are the researcher's responsibilities; this draft app does not authorize a human study.

A guided start can preload the same pinned configuration:

```sh
./start.sh --study-config study.json --config-sha256 RESEARCHER_PROVIDED_HASH
```

This guided command explicitly opts into local processing; history sharing remains off unless `--share-history` is supplied. The browser setup form offers the same choices without command-line flags.

## What is frozen

The exact M0 package is vendored in [`contracts/offline_bundle/v1`](contracts/offline_bundle/v1/README.md), release digest:

`2c7db223667618d3c9f935ca55a76c62cd4171d93987ee6b59f422768f9fa574`

Do not edit vendored contract files. The two pure behavioral sources are byte-identical to M0's implementation pins. Only a tiny timestamp helper and the v0.3 JSON driver were extracted with them. No research ORM, credentials, investigator prompts, audio or personal profiles were copied. See [provenance and verification](docs/verification.md).

## Tests

```sh
.venv/bin/python -m contracts.offline_bundle.v1.selftest
.venv/bin/python -m unittest discover -s tests -v
```

Developer-only browser tests require build-time installation (not participant runtime):

```sh
npm ci --ignore-scripts
npx playwright install chromium
npx playwright test
```

The GitHub acceptance workflow installs dependencies first, then runs unit/contract/browser tests in a fresh Linux network namespace with **only loopback available**. It exercises setup, history upload, draft recovery after server restart, neutral locking, optional questions, encrypted download, M0 decryption/validation and a second restart. Synthetic fixtures only; the temporary test decryption identity never enters participant app storage or Git.

## Local deletion and transferred copies

The app's deletion control removes its local records, sampling runs, drafts, cached exports and SQLite contents, using SQLite secure deletion and WAL truncation. It does not delete original Spotify files, browser downloads, other backups or researcher-held copies. Contact the researcher separately for withdrawal after transfer. No universal SSD/backup erasure or deletion from already disseminated anonymous research is promised.
