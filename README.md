# Clinical Record Conformance

A public reconstruction of a two-layer clinical documentation conformance pipeline: public national requirements provide the baseline, while a wholly synthetic departmental template defines the evaluation fields and implementation-specific constraints. The repository contains no private source code, hospital template, patient data, or institutional result.

Prompt-only free-text generation achieved the highest raw conformance rate, at the cost of inventing content for 10 of 12 fields absent from the source. The source-aware constrained pipeline had lower raw conformance, and that was the correct behavior: it exposed 11 missing facts as violations instead of silently completing them. Retries recovered 100% of model extraction or formatting failures and 0% of source-information absences, so the validator should route failures, not blindly retry them.

The paired input-shape experiment was a null result. Synthetic fragmentation rearranged and interrupted the facts but preserved them; it did not consistently reduce conformance. In Arm C, fragmented input was nominally higher on raw conformance by one record out of 20, but that record passed by filling an absent visit time. On the joint metric, narrative and fragmented Arm C were both 70%, and both reached 100% on the 14 complete-source pairs. This benchmark therefore separates two mechanisms: information loss produces visible gaps, while word-order disruption alone did not show a consistent effect.

| Arm | Method | **Conformant and grounded** | Raw conformance | Source-grounded records | Required-field population | Unsupported fills | Cost |
|---|---|---:|---:|---:|---:|---:|---:|
| A | Prose standard, free-text output | **78.3%** | 93.3% | 83.3% | 100.0% | **10 / 12** | $0.1958 |
| B | Strict JSON template, one attempt | **76.7%** | 76.7% | 98.3% | 98.3% | **1 / 12** | $0.3525 |
| C | JSON template plus source-aware validator loop | **80.0%** | 81.7% | 98.3% | 98.3% | **1 / 12** | $0.3704 |

`conformant_and_grounded` requires both a clean validator result and no unsupported fill of a manifest-controlled omission. Changing from raw conformance to this joint metric reverses the A-versus-C ranking. It is deliberately narrower than a general factuality score: the benchmark can mechanically judge only the fields it intentionally omitted. “Required-field population” likewise means that a required section contains text; it does not imply that the text is complete, correct, or supported.

The full Arm C pipeline cost **1.9×** as much as prompt-only Arm A. That is the observed cost of the entire constrained pipeline, not a causal price for grounding alone: template-only Arm B already accounts for most of the gap, while C's three second attempts added **5.1%** over B. The trade-off is therefore explicit rather than free—better source grounding and failure routing required more inference spend.

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

| Arm | Narrative raw conformance | Fragmented raw conformance | Narrative conformant + grounded | Fragmented conformant + grounded |
|---|---:|---:|---:|---:|
| A | 95.0% | 85.0% | 70.0% | 65.0% |
| B | 60.0% | 70.0% | 60.0% | 70.0% |
| C | 70.0% | 75.0% | 70.0% | 70.0% |

The input-shape hypothesis was not supported, and the nominal direction for B and C was opposite to the original expectation. The C difference in raw conformance is only one record: fragmented `em_15` passed after populating an absent visit time with the treatment timestamp, while `em_narrative_15` left the field empty and correctly failed. Once conformance and grounding are combined, both C conditions are 70%. After excluding the six emergency cases with intentional source omissions, Arm C is 100% on both sets.

This is a useful limit on the conclusion. The synthetic “fragmented” dictations reorder, interrupt, correct, and repeat observations, but they do not delete facts. The experiment therefore tests disorder without information loss. It suggests that source omission—not fragmented word order by itself—is the mechanism this benchmark can demonstrate. It does not establish which mechanism dominates real emergency dictation or ASR failures.

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

Arm C's observed median (2163 ms) is lower than Arm B's (2395 ms), despite C making three additional calls. That ordering is small-sample API latency noise, not evidence that retries are free. Their cost appears in the 1.9× A-to-C spend, the 5.1% B-to-C increment, and the three records whose end-to-end latency includes a second call.

## Run it

This is an offline batch experiment, not a service. There is no HTTP entrypoint and nothing to deploy: `src.generate` runs the three arms once and writes JSONL, and `src.evaluate` recomputes the metrics from a committed run. The numbers above come from `results/final_run.jsonl`, which is in the repository, so every table can be reproduced without an API key.

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
