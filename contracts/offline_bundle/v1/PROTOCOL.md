# Resonance offline retrospective MVP protocol

Version: **offline-retro-mvp-1.0.0-draft**. Status: **DRAFT pilot, not preregistered, not an approved recruitment/consent protocol**. Exchange: `resonance-bundle/1.0.0`.

This is the authoritative protocol for the two-repository offline retrospective MVP. The earlier v3 staff-hosted pilot remains a separate historical protocol; its completed runs and protocol hashes are not rewritten. This document, executable schemas, questions and sampling configuration are one frozen release. The specifications are maintained here, then vendored verbatim into each application; neither app maintains an independently edited copy.

## Architecture and scope

The existing private Resonance repo remains the research/admin engine. A future clean participant repository will perform local ingestion, frozen behavioral selection, interviews and encrypted manual export without a research-server connection. Installation/build may use the internet; study operation must not. M0 supplies the contract and reference codec/importer; it does not create or publish that participant application.

The existing v0.3 and PED implementations are unchanged. This pilot tests mapped-window selection policies, not psychological diagnoses or hidden motivational labels. Cue analysis, lyrics/audio enrichment and the LLM investigator cannot influence selection or neutral questions and are not begun by M0.

## Primary question and interpretation

With comparable invitation/question burden, does PED select historical listening periods with greater participant-rated event-specific meaningfulness than Random or v0.3? No benefit is assumed. Pilot results are descriptive, not confirmatory. Retrospective recollection is not prospective EMA. Unknown, non-recalled, not-applicable and declined responses are distinct from low meaningfulness. Recognition, response availability and burden must be reported separately by arm.

A future confirmatory protocol requires piloted instrument wording, a power/analysis plan, independent measurement review and the appropriate ethics determination. M0 freezes a technical pilot instrument, not a validated construct measure.

## Source history and common eligible universe

Freeze a consented historical input set and `sampling_cutoff_at` before ranking. Source records use provider timestamp semantics; END timestamps are not silently treated as starts. Keep observed and estimated clocks separately. Unknown skips remain null, never false; non-skip does not establish enjoyment or deliberate selection. No audio exposure position is inferred from duration.

Sort normalized events by `(occurred_at, source_ordinal, event_key)`. Ties are deterministic, not evidence of actual temporal precedence. An event key is SHA-256/JCS of its original source-file digest and ordinal. Divide events at a gap strictly greater than 1,800 seconds or a historical UTC-day boundary. In each resulting session/day span, enumerate consecutive chunks of four events; retain a final chunk of three. Retain shorter chunks as INELIGIBLE (`TOO_SHORT`), spans over 1,800 seconds as INELIGIBLE (`SPAN_TOO_LONG`), and windows crossing the historical completion cutoff as INELIGIBLE (`AFTER_CUTOFF`). Keep every exclusion. All arms use the same eligible universe.

Native results are separate immutable records. Preserve every native candidate, implementation/version, raw score, reasons, membership and original payload, including unselected candidates. Rank each native arm by descending score, ties by candidate key. Map a common window to all overlapping native candidates using exact event keys; its mapped score is the maximum reciprocal native rank, or zero when unmatched. Random ignores those scores. This is explicitly a common-window policy comparison; it does not pretend native geometries were identical. The shared reference `sampling.py` defines the mapping without modifying either surfacer.

## Collection-day randomization

The unit is **participant collection-day prompt slot**, not the historical episode day. V1 uses UTC collection dates and at most **one slot per collection day**. Store `collection_day`, timezone, slot ordinal and actual device-reported decision time independently from historical dates. An installation on October 30 may ask about March events; March dates do not create October daily prompt capacity.

Before the first neutral response, precommit an enrollment seed independently of outcomes. Store it and its SHA-256/JCS commitment; all slots use that seed. The contract can verify the declared commitment and deterministic replay, not independently prove when a participant-controlled machine first chose it. Enrollment/release procedures must establish the precommitment out of band before comparative collection; searching seeds after seeing outcomes invalidates the design.

For each slot, remove already invited event overlaps before freezing its frame. Draw uniformly among available arms with `jcs-sha256-rejection-v1`; the draw unit includes study, participant pseudonym, **collection** day and slot ordinal. RANDOM draws uniformly from the frame. v0.3/PED choose their top mapped score, breaking ties by ascending window key. Preserve all mappings, native candidates, unselected windows, frame hash and prior assignments. Empty frames produce no invitation. Repeated exports contain the cumulative immutable assignment ledger; imports reject omitted earlier assignments, changed identities in an occupied slot and duplicate event invitations.

For N eligible remaining windows and K available arms, arm assignment probability is `1/K`. Conditional window probability is `1/N` for Random, or the point mass at a deterministic arm's frozen winner. Step inclusion probability is the average of those per-arm probabilities for that window. It is explicitly conditional on the frozen remaining frame and recorded previous assignments. **Cumulative trial-wide inclusion probability is null**; this release does not invent it. With all three arms available, the usual expression is `(1/N + I[v0.3 winner] + I[PED winner])/3`. If an arm is unavailable, label the run FEASIBILITY_ONLY; it is not a full three-arm comparison. Source data being withheld also prevents independently verifying eligibility/scoring, even when declared assignments can be reproduced from the snapshots.

## Neutral measurement and follow-ups

The authoritative wording, anchors, response choices, order and versions are in `questions.json`:

1. Episode recognition, required, with clear/vague/non-recall/unsure/not-applicable/declined choices.
2. Event-specific personal meaningfulness, required, 1–7 with fixed anchors and separate unknown/non-recall/not-applicable/declined responses.

A required item means an explicit response/status, not a forced numeric answer. If recognition is non-recalled/unsure/not-applicable/declined, meaningfulness retains that status and null numeric value. No conversion to 1 or zero.

Neutral submission, immutable answers, answer-set hash and lock commit atomically on the participant device before any follow-up is returned. Packet definitions predeclare the allowed follow-up IDs; they are not evidence of exposure. A FOLLOWUP_SHOWN audit includes the exact rendered version/wording and the prior neutral lock. At most two distinct adaptive follow-ups may be shown; both have their own question versions and optional uncertainty/decline responses. Follow-up submissions are separate from neutral submissions and cannot replace primary answers. Additional neutral items require a new piloted question-bank/protocol version.

State machine: `CREATED -> NEUTRAL_OPEN -> NEUTRAL_LOCKED -> FOLLOWUP_OPEN -> FOLLOWUP_LOCKED -> COMPLETED`, with optional completion directly after neutral lock, or without answering optional follow-ups. Decline/expiry is allowed before neutral lock. No events may reopen a terminal state. Identical retried submissions reuse the same immutable identity/content; a changed value under that identity conflicts. The importer never repairs, rerenders or regenerates the participant's answers or invitation history.

Audit sequences, lock sequences, device wall clocks and actual research receipt clocks remain distinct. Sequences prove declared transaction order within the record set, not a trusted hardware attestation. Device clock timestamps are labeled `DEVICE_REPORTED_NOT_INDEPENDENTLY_VERIFIED`; preserve them verbatim.

## Export, consent and transfer

No auto-upload, telemetry, remote schema lookup or remote inference. Runtime assets must be local. The M0 codec is tested with Python/Node network entry points disabled; full packaged participant-app airplane-mode acceptance remains an M1 gate.

The draft consent template is `consent.json`, with separate explicit response and history grants and no grants selected by default. The participant sees the full export contents, section counts/digests, scope and withdrawal notice, then explicitly confirms encrypted export. Preview and consent bindings are validated before age encryption. The versioned codec accepts only the allowlisted logical records and archive paths. Original provider files, account emails, tokens, IP/GPS/device identifiers, filesystem paths and private research prompts are not exported. Free text and music titles can still be sensitive; preview is required.

Use authenticated age v1 X25519 recipient encryption through the pinned `pyrage` implementation. Pin the recipient public key fingerprint through an authenticated deployment configuration; the unconfigured study template has export disabled. The private identity remains outside this repository and outside participant distributions. The public fixture key is deliberately synthetic/test-only and must never be used for a study. Ciphertext integrity is not proof of participant identity or honesty; enrollment alias verification is out of band. Key provisioning, release authentication/signing and installer packaging are deployment/M1 gates, not completed human-study authorization.

## Responses-only evidence and import preservation

RESPONSES_ONLY omits ingestion files. Preserve historical episode/prompt evidence snapshots, native proposals/mappings, assignments, rendered questions, device timestamps, source IDs, answers and locks without inventing listening events or a reference-event FK. Mark source history `WITHHELD_UNVERIFIABLE`. The admin can reproduce the declared mapping/draw over supplied snapshots, but cannot certify that withheld source data or detector scoring was correct.

Dedicated import validates authenticated decryption, archive limits/checksums, schemas, references, consent, question versions, state order and hashes before canonical writes. Source identities map to immutable evidence, with existing observations/forms materialized only where appropriate. Research events become available on the research machine at actual receipt, while original participant/source availability remains in the retained source record. Acknowledgment receipts preserve actual import time separately. Identical bundle/content retries are no-ops; repeated records across cumulative exports reuse prior evidence. Different content under an existing bundle/submission/record identity conflicts atomically. The importer never runs a surfacer. Later research recomputation is explicitly diagnostic and cannot change actual invitations or treatment assignments.

Exact record/bundle integrity uses RFC 8785 and SHA-256, excluding only its own containing hash field. Scientific identity is a separate documented projection that excludes containing source-record IDs, creation/generation/import clocks and cached record hashes and remaps source references to semantic parents; relevant historical/availability/decision/response clocks, question content, input versions, settings and seed remain included. Input records and exact integrity are retained alongside it. No hash is treated as an authorship signature.

## Withdrawal and retention

Local deletion covers local data and files the participant application controls, not transferred copies. After transfer, a separate researcher withdrawal request must erase or irreversibly sever personal raw data, captures, forms, derived analyses/caches/models, affected frozen datasets and controlled exports. The existing research erasure workflow applies to imported captures and retains non-content enrollment tombstones to prevent reimport after withdrawal. Shared public recording metadata may remain for other participants.

Keep backups isolated for at most 30 days after withdrawal, destroy earlier where possible, and reapply the current tombstone ledger before serving restored data. Downloaded/unmanaged copies and backups require actual deletion and operator attestations; jobs remain retention-pending until those actions are recorded. Do not promise erasure from every device, SSD remnant, external backup or already disseminated anonymous publication. These draft retention commitments require approval under the real study's consent/ethics process before collection.

## Analysis and acceptance gates

Report invitations, opening/completion, recognition/missingness, ordinal meaningfulness, recall lag and burden by arm. Do not rank policies by candidate counts, synthetic labels or explanatory fluency. Any threshold, mixed ordinal model, power target or confirmatory contrast requires a separately frozen analysis plan after pilot measurement work.

M0 acceptance: executable schemas; exactly versioned neutral/follow-up bank; common-universe/mapping/collection-slot policy; valid, invalid and hostile fixtures; independent Python/JavaScript JCS vectors including RFC numeric edge cases; exact preservation, idempotency/conflict, responses-only, encryption/consent, network-denial and withdrawal compatibility tests; a locked artifact manifest and exportable release. Existing surfacer code hashes must remain unchanged. No participant app or advanced cue/investigator engine is created by M0.
