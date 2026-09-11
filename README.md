<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Clinical Record Conformance benchmark comparing three documentation generation pipelines">
</p>

An offline research benchmark for a simple but consequential question: **does a more conformant clinical note remain grounded in the facts it was given?**

The repository compares prompt-only prose, strict structured output, and a source-aware validator loop on 60 wholly synthetic records. It contains no patient data, hospital templates, private code, or institutional results.

## Result at a glance

| Arm | Method | Conformant + grounded | Raw conformance | Grounded records | Unsupported fills | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A | Prose standard, free-text output | 78.3% | **93.3%** | 83.3% | **10 / 12** | $0.1958 |
| B | Strict JSON, one attempt | 76.7% | 76.7% | **98.3%** | **1 / 12** | $0.3525 |
| C | JSON + source-aware validator loop | **80.0%** | 81.7% | **98.3%** | **1 / 12** | $0.3704 |

Prompt-only generation looked best on raw conformance because it silently completed missing facts. The ranking reverses on the joint metric: Arm C is the strongest pipeline when a record must both pass validation and avoid manifest-controlled unsupported fills.

These values are recomputed from [`results/final_run.jsonl`](./results/final_run.jsonl): 60 records generated with `gpt-4o-2024-08-06`, seed 7, and temperature 0.2. The full [report](./results/report.md) includes per-rule, latency, cost, recovery, grounding, and human-review details.

## What the benchmark isolates

### Missing information

[`data/manifest.json`](./data/manifest.json) records every intentionally omitted required field and its expected rule violation. A plausible value in an omitted field is counted as an unsupported fill, even when it sounds clinically reasonable.

| Failure diagnosis | Initial instances | Recovered |
| --- | ---: | ---: |
| Model extraction or formatting | 3 | **3 / 3** |
| Source information absent | 11 | **0 / 11** |

That zero is correct behavior: retries can repair model formatting, not recover facts that never existed in the source.

### Input shape

Each of 20 emergency cases has an ordered narrative and a fragmented counterpart with the same source-fact fingerprint. Fragmentation rearranges and repeats facts without deleting them.

The paired result was null. Arm C reached 70% conformant + grounded in both conditions, and 100% in both after excluding the six pairs with intentional source omissions. The benchmark demonstrates source omission as a failure mechanism; it does not show that word-order disruption alone consistently reduces conformance.

## Reproduce it

Python 3.11 or newer is recommended.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Recompute the published metrics without an API key and run the deterministic tests:

```bash
.venv/bin/python -m src.evaluate results/final_run.jsonl
.venv/bin/python -m pytest -q
```

To generate a new three-arm run, set `OPENAI_API_KEY` in `.env` and run:

```bash
.venv/bin/python -m src.generate
```

Interrupted runs can resume with `python -m src.generate --resume-log results/run_<timestamp>.jsonl`.

## Design

- [`schemas/`](./schemas/) separates public-clause provenance from a fictional departmental evaluation layer.
- [`src/validator.py`](./src/validator.py) implements deterministic required, length, pattern, numeric, ordering, and timestamp checks without model calls.
- [`src/generate.py`](./src/generate.py) runs the three arms and routes failures by root cause.
- [`src/evaluate.py`](./src/evaluate.py) and [`src/report.py`](./src/report.py) calculate the joint metric, recovery, conformance, grounding, latency, and cost.
- [`tests/`](./tests/) covers provenance, corpus pairing, omissions, feedback, validation, pipeline behavior, and resume semantics.

The public baseline maps selected rules to the National Health Commission's [Basic Standards for Medical Record Writing](https://www.nhc.gov.cn/yzygj/c100068/201002/766b58f0dd9242d3b62276e5c88d27dc.shtml). Exact field layouts, character limits, terminology, ordering, and disposition vocabulary are synthetic evaluation choices.

## Scope

This is an evaluation artifact, not a clinical product. It has no EHR integration, user interface, deployment service, agent framework, or protected health information. Its synthetic rules and findings must not be used for clinical, compliance, or documentation decisions.
