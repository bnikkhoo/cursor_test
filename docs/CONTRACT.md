# PFA Intake Engine — CLI Contract

For future Chief of Staff / FSP wiring. **This repo does not call live bots and does not change them.**

Data directory: `$PFA_INTAKE_DATA` or `--data PATH` (default `./data`).

All commands print JSON on stdout. Secrets (card PAN/CVV, gov IDs, passwords) must never appear in `--json`, evidence, or notes — last 4 only for cards.

## Commands

### `upsert`

Create or update a work item.

```bash
pfa-intake upsert --json '{
  "person_name": "Jane Doe",
  "doc_class": "photo_id",
  "status": "waiting_person",
  "owner_bot": "fsp",
  "stage": "day3",
  "next_action": "send reminder",
  "next_action_at": "2026-11-07",
  "day0": "2026-11-04",
  "step_code": "D3"
}'
```

Enums: see `pfa_intake.schemas` (`DocClass`, `WorkStatus`, `OwnerBot`, `ReplyStatus`).

### `get` / `list`

```bash
pfa-intake get --person "Jane Doe" --doc-class photo_id
pfa-intake list --open
```

### `check`

Before any reminder / chase / follow-up. Exit `0` if skip (already done); `2` if not done.

```bash
pfa-intake check --person "Parked Pilot" --item medical
# {"done": true, "skip": true, "reason": "completed:verified", ...}
```

Done actions: `completed`, `uploaded`, `verified`, `closed`, `returned`, `filed`.  
`reopened` cancels a prior done. `sent` / `received` are history only.

### `complete`

Append to the audit log; marks matching work item `done` for done-actions.

```bash
pfa-intake complete --bot fsp --person "Jane Doe" --item photo_id \
  --action uploaded --evidence "fsp:row-reload-ok"
```

### `decide-mail`

Pure triage. Does **not** send, file, or tag.

```bash
pfa-intake decide-mail --json '{
  "channel": "fly",
  "subject": "Action needed: Photo ID",
  "from_address": "jane@example.com",
  "has_attachment": false,
  "sender_in_tracker": true
}'
```

Channels: `fly` | `grokbot` | `we_app`.  
For WE, set `we_form_type`: `passenger_waiver` | `membership_agreement` | `membership_agreement_minor` | `aoa` | `bluetooth` | `ppp`.

Result: `{decision, route, reason, work_item_patch?, fd_queue_line?, waiver_check_fields?}`.

### `chase-due`

```bash
pfa-intake chase-due --as-of 2026-11-15
# {"as_of":"2026-11-15","actions":[{work_item_key, person_name, doc_class, step_code, channel, reason, next_action_at}]}
```

One email per person per day; catch-up = latest due step only; replies / snooze / audit-done / Email List (except agreements) stop chase.

### `fd-queue`

Derived Front Desk lines. **Detail is rewritten when stage advances** (`advance`).

```bash
pfa-intake fd-queue
pfa-intake advance --key "jane_doe|photo_id" --stage day7 --next-action "final reminder" --notes "Day 7 SMS via Dialpad"
```

### `import-legacy`

Fixture / export import only (never reaches into the live Grok box by itself).

```bash
pfa-intake import-legacy \
  --tracker fixtures/tracker.csv \
  --queue fixtures/queue.jsonl \
  --completions fixtures/completions.jsonl
```

## Suggested bot adoption (later, explicit)

1. CoS fly@ scan: call `decide-mail` → act in Outlook/FSP/WE → `upsert` / `complete`.
2. FSP chase morning: `check` then `chase-due` → send batch → `complete` with `sent` (history) or done-actions when uploaded.
3. CoS 8:07 / 2:17 posts: read `fd-queue` instead of raw append-only `queue.jsonl`.

No adoption happens until you ask to wire it on the box.
