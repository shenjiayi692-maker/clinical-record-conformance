# Clinical Record Conformance

A public reconstruction of a schema-driven clinical documentation conformance pipeline. It compares prompt-only generation, JSON-template generation, and deterministic validator feedback on 40 entirely synthetic Chinese dictations. No private source code, production schema, patient data, or institutional result is included.

| Arm | Method | Overall pass rate | Emergency | Internal medicine | Estimated cost |
|---|---|---:|---:|---:|---:|
| A | Prose standard, free-text output | 75.0% | 50.0% | 100.0% | $0.1246 |
| B | Strict JSON template, one attempt | 85.0% | 70.0% | 100.0% | $0.2268 |
| C | JSON template plus validator feedback, up to three attempts | **87.5%** | **75.0%** | **100.0%** | $0.2950 |

These are the results of the committed seeded run in [`results/final_run.jsonl`](results/final_run.jsonl), using `gpt-4o-2024-08-06`, seed 7, and temperature 0.2. The full latency, completeness, retry, per-rule, and unrecoverable-case breakdown is in [`results/report.md`](results/report.md).

## What the experiment tests

All three arms receive the same synthetic source facts and an explicit instruction not to invent missing information.

- Arm A receives the department standard in prose and returns free text. Its output is parsed from section labels before validation; malformed or unknown headings produce `PARSE-000`.
- Arm B receives a strict department JSON template and has one attempt.
- Arm C starts from the same JSON-template prompt. When deterministic validation fails, a new stateless request receives only the violated rules' messages and may try again, up to three attempts total.

The template improved overall conformance by 10 percentage points over free text. The validator loop recovered one additional emergency record, moving emergency conformance from 70% to 75%. Five Arm C emergency records remained invalid after three attempts because their source dictations omitted required facts; the loop leaves those fields blank instead of hallucinating them.

Internal-medicine dictations are continuous, ordered, and information-complete, so every arm passed all 20 records. Emergency dictations are deliberately fragmented and out of order, include interruptions and duplicate observations, and omit required source information in 6 of 20 cases. This produces the observed department gap without using real patient data.

## Deterministic conformance layer

The schemas in [`schemas/`](schemas/) define ordered sections and stable rule IDs. The validator in [`src/validator.py`](src/validator.py) makes no model calls and supports only a deliberately small rule vocabulary:

- `required`, `min_length`, and `max_length`
- `must_match` and `must_not_match`
- `numeric_fields`
- `section_order`
- `timestamp_format`, fixed to `YYYY-MM-DD HH:MM`

Validation returns every violated ID in schema order. JSON values must be strings, unknown fields and unparseable free text produce `PARSE-000`, and disposition values are checked with anchored regular expressions. Both reconstructed schemas retain a top-level `TODO-VERIFY` marker so their field definitions cannot be mistaken for an authoritative production standard.

## Run it

Python 3.11 or newer is recommended.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Put an OpenAI API key in `.env` as `OPENAI_API_KEY`. Then run the complete experiment with one command:

```bash
.venv/bin/python -m src.generate
```

Every attempt is appended immediately to a timestamped JSONL file. The log records the record, arm, department, attempt number, violated rule IDs, latency, tokens, estimated cost, requested and returned model, system fingerprint, seed, temperature, and timestamp. If a transient API limit interrupts a run, resume it without changing the configuration:

```bash
.venv/bin/python -m src.generate --resume-log results/run_<timestamp>.jsonl
```

To validate the local implementation without API calls:

```bash
.venv/bin/python -m pytest -q
```

To recompute metrics from the committed run:

```bash
.venv/bin/python -m src.evaluate results/final_run.jsonl
```

The model snapshot, seed, temperature, and system fingerprint are logged for auditability. Seeded model output should still be treated as best-effort reproducibility; the validator and metric computation themselves are deterministic.

## Repository contents

- [`data/dictations/`](data/dictations/) — 20 synthetic internal-medicine and 20 synthetic emergency dictations
- [`schemas/`](schemas/) — reconstructed department schemas with stable rule IDs
- [`src/generate.py`](src/generate.py) — three-arm generation, feedback, retry, resume, and attempt logging
- [`src/validator.py`](src/validator.py) — deterministic parser and validator
- [`src/evaluate.py`](src/evaluate.py) and [`src/report.py`](src/report.py) — metrics and Markdown reporting
- [`tests/`](tests/) — validator, corpus, pipeline, and resume tests

## Scope

This repository is an evaluation artifact, not a clinical product. It does not contain a user interface, agent framework, vector database, EHR integration, deployment configuration, or protected health information. The reconstructed rules are illustrative and must not be used to make clinical, compliance, or documentation decisions.
