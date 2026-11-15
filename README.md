# PFA Document Intake Engine

Deterministic sidecar for Pacific Flight Academy document intake: one work-item store, typed schemas, fly@ / WaiverElectronic **decision** logic, chase stop-conditions, and Front Desk queue views.

## Live bots unchanged

This repository does **not** modify Chief of Staff, FSP, Badge Manager, Dialpad, or any Grok Bot prompts, schedules, or box files. Adoption is opt-in: copy the CLI onto the box later, or wire bots to call it. Until then, this package only runs against local fixtures / a local data directory.

## Install

```bash
python3 -m pip install -e ".[dev]"
```

## CLI

```bash
export PFA_INTAKE_DATA=./data   # optional; default ./data
pfa-intake upsert --json '{"person_key":"doe_jane","person_name":"Jane Doe","doc_class":"photo_id","status":"waiting_person","owner_bot":"fsp"}'
pfa-intake check --person "Jane Doe" --item photo_id
pfa-intake decide-mail --json '{"channel":"fly","subject":"Action needed: Photo ID","from_address":"jane@example.com","has_attachment":false}'
pfa-intake chase-due --as-of 2026-11-15
pfa-intake fd-queue
pfa-intake complete --bot fsp --person "Jane Doe" --item photo_id --action uploaded --evidence "fsp:demo"
pfa-intake import-legacy --tracker fixtures/tracker.csv --queue fixtures/queue.jsonl --completions fixtures/completions.jsonl
```

See [docs/CONTRACT.md](docs/CONTRACT.md) for the full command contract.

## Tests

```bash
python3 -m pytest -q
```

## Scope (Slice 1)

In scope: work items, audit log, fly@/WE triage decisions, chase stop/next-action, Front Desk derived queue, legacy fixture import.

Out of scope: browser automation, Outlook send/file, WE tagging, Badge Manager lifecycle, WhatsApp, Dialpad, stage checks.
