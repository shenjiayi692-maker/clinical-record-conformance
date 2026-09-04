# Clinical Record Conformance

A public reconstruction of a two-layer clinical documentation conformance pipeline: public national requirements provide the baseline, while a wholly synthetic departmental template defines the evaluation fields and implementation-specific constraints. The repository contains no private source code, hospital template, patient data, or institutional result.

| Arm | Method | Raw conformance | Source-grounded records | Unsupported fills | Field completeness |
|---|---|---:|---:|---:|---:|
| A | Prose standard, free-text output | 93.3% | 83.3% | **10 / 12** | 100.0% |
| B | Strict JSON template, one attempt | 76.7% | 98.3% | **1 / 12** | 98.3% |
| C | JSON template plus source-aware validator loop | 81.7% | 98.3% | **1 / 12** | 98.3% |

The headline is not that free text “won” on conformance. Arm A looked complete because it populated 10 of 12 required fields or subfields that the source dictations deliberately omitted. Arm C left 11 of 12 absent facts unpopulated and surfaced them as violations. In this setting, making missing information visible is more important than maximizing a pass rate.

These numbers come from the committed 60-record run in [`results/final_run.jsonl`](results/final_run.jsonl), using `gpt-4o-2024-08-06`, seed 7, and temperature 0.2. The 183-line attempt log and [`results/report.md`](results/report.md) contain latency, cost, grounding, per-rule, recovery, and human-review details.

## Public standard and synthetic template

Every rule has a `source` field. The two allowed provenance layers are intentionally different:

- Public baseline: the National Health Commission's [《病历书写基本规范》](https://www.nhc.gov.cn/yzygj/c100068/201002/766b58f0dd9242d3b62276e5c88d27dc.shtml), issued as 卫医政发〔2010〕11号. Rule mappings cite the applicable article, including Article 9 for numeric 24-hour date/time notation, Articles 12–15 for outpatient and emergency records, and Article 18 for admission-record content definitions.
- Department layer: `illustrative departmental template (synthetic)`. Section layout, exact character limits, ASCII vital-sign encoding, closed disposition vocabulary, treatment timestamp rule, and section order are fictional evaluation choices. They do not transcribe a customer's template.

For example:

```json
{
  "id": "IM-REQ-001",
  "type": "required",
  "source": "《病历书写基本规范》第十八条第（二）项",
  "message": "主诉不得为空"
}
```

The top-level `provenance` object in each file documents both layers, and schema loading fails if a rule lacks `source`. The schemas remain evaluation subsets rather than complete clinical-record specifications.

## Ground truth for missing information

[`data/manifest.json`](data/manifest.json) records the dictation path, case ID, input style, source-fact fingerprint, intentionally omitted required fields, and the rule ID expected to expose each omission. Dot notation represents a required subfield such as `vital_signs.SpO2`.

This makes unsupported completion mechanical rather than subjective: if the manifest says a fact is absent and the generated field contains it, the evaluator counts an unsupported fill. Plausible phrases such as “no known allergies,” inferred arrival times, or guessed dispositions do not receive credit.

One Arm C first attempt still populated an absent fact. The manifest caught it. Prompt instructions alone therefore do not guarantee grounding; the benchmark keeps this failure visible rather than post-processing it away with ground-truth knowledge.

## Validator as a diagnostic layer

Arm C does not retry every failure:

- `required` failures are routed directly to `human_review_rule_ids`.
- A `numeric_fields` failure is also routed to human review when the source dictation lacks one of the required numeric facts.
- Only model-repairable parse, formatting, terminology, or ordering failures are returned as rule messages in a new stateless generation request, with a maximum of three attempts.

This policy prevents the validator from pressuring the model to invent missing values. In the committed run:

| Failure diagnosis | Initial instances | Recovered | Recovery rate |
|---|---:|---:|---:|
| Model extraction or formatting | 3 | 3 | **100.0%** |
| Source information absent | 11 | 0 | **0.0%** |

The apparent `EM-FMT-402` retry failure in the earlier design was not a broken feedback path. The source omitted `SpO2`; the corrected pipeline classifies that numeric-format violation by root cause and sends it to human review without retrying. Regression tests cover both cases: absent `SpO2` does not retry, while a value present in the source but omitted by the model does receive feedback and can be repaired.

## Paired emergency input-shape control

The 20 emergency cases are each rendered twice from the same source-fact object and share an identical SHA-256 fact fingerprint. One version is ordered narrative; the other is fragmented, interrupted, and includes corrections and duplicate observations. Both use the same emergency schema.

| Arm | Narrative conformance | Fragmented conformance | Narrative source-grounded | Fragmented source-grounded |
|---|---:|---:|---:|---:|
| A | 95.0% | 85.0% | 75.0% | 75.0% |
| B | 60.0% | 70.0% | 95.0% | 100.0% |
| C | 70.0% | 75.0% | 100.0% | 95.0% |

The input-shape effect was not consistent across arms. After excluding the six emergency cases with intentional source omissions, Arm C reached 100% on both sets; A favored narrative by 7.1 percentage points, while B favored fragmented input by 14.3 points. This run therefore does not support a blanket claim that fragmentation alone reduces conformance. It does remove the earlier confound between emergency schema size and emergency dictation shape.

Arms B and C had identical aggregate first-attempt failure counts by rule. At record level, failure sets matched for 55 of 60 records and structured outputs for 43 of 60. The model snapshot, seed, and temperature reduce variation but do not make API output bitwise deterministic, so retry recovery is measured within Arm C from its own first attempt to its final attempt.

## Deterministic conformance layer

The validator in [`src/validator.py`](src/validator.py) makes no model calls and supports a deliberately small rule vocabulary:

- `required`, `min_length`, and `max_length`
- `must_match` and `must_not_match`
- `numeric_fields`
- `section_order`
- `timestamp_format`, fixed to `YYYY-MM-DD HH:MM`

Validation returns every violated ID in schema order. JSON values must be strings, unknown fields and unparseable free text produce `PARSE-000`, and dispositions use an anchored closed-set expression. The free-text parser removes sentence-ending punctuation before validating a closed-set field, so `收入院。` is parsed as the value `收入院` without weakening strict JSON validation.

## Latency reporting

The report uses median and observed maximum latency, not p95. With 20 records per paired condition, p95 would mostly describe one API tail. Every maximum is shown with its record ID and API-call count; Arm C latency is end-to-end and includes retries.

## Run it

Python 3.11 or newer is recommended.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Put an OpenAI API key in `.env` as `OPENAI_API_KEY`, then run the full experiment:

```bash
.venv/bin/python -m src.generate
```

Every attempt is appended immediately to a timestamped JSONL file. If a transient API limit interrupts the run, resume it with the same configuration:

```bash
.venv/bin/python -m src.generate --resume-log results/run_<timestamp>.jsonl
```

Run the deterministic test suite without API calls:

```bash
.venv/bin/python -m pytest -q
```

Recompute metrics from the committed run:

```bash
.venv/bin/python -m src.evaluate results/final_run.jsonl
```

## Repository contents

- [`data/dictations/`](data/dictations/) — 20 internal-medicine narratives and two matched versions of 20 emergency cases
- [`data/manifest.json`](data/manifest.json) — source omissions, matched-case IDs, and fact fingerprints
- [`schemas/`](schemas/) — public-clause provenance plus synthetic departmental templates
- [`src/generate.py`](src/generate.py) — three arms, source-aware retry routing, resume, and attempt logging
- [`src/validator.py`](src/validator.py) — deterministic parser and validator
- [`src/evaluate.py`](src/evaluate.py) and [`src/report.py`](src/report.py) — grounding, recovery, conformance, and latency reporting
- [`tests/`](tests/) — provenance, corpus pairing, grounding, feedback, validator, pipeline, and resume tests

## Scope

This is an evaluation artifact, not a clinical product. It has no user interface, agent framework, vector database, EHR integration, deployment configuration, or protected health information. The synthetic departmental rules must not be used for clinical, compliance, or documentation decisions.
