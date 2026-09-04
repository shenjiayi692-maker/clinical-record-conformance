# Clinical record conformance evaluation

Source log: `results/final_run.jsonl`

## Headline: conformance without invention

Prompt-only Arm A achieved the highest raw conformance at **93.3%**, while populating **10 of 12** fields absent from the source. Arm C's lower raw conformance of **81.7%** was often the safer behavior: it left **11** controlled omissions unpopulated and surfaced **11** as violations. Retries recovered **100.0%** of model extraction or formatting failures and **0.0%** of source-information absences, so the validator should route failures rather than blindly retry them.

| Arm | Records | **Conformant and grounded** | Raw conformance | Source-grounded records | Required-field population | Unsupported fills | Total estimated cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| A — prompt only | 60 | **78.3%** | 93.3% | 83.3% | 100.0% | 10 | $0.1958 |
| B — template constrained | 60 | **76.7%** | 76.7% | 98.3% | 98.3% | 1 | $0.3525 |
| C — template + validator loop | 60 | **80.0%** | 81.7% | 98.3% | 98.3% | 1 | $0.3704 |

**Conformant and grounded** means that the final record passed every rule and did not populate any manifest-controlled omission. This is stricter than raw conformance, but it is not a general factuality score: grounding is measured only for the benchmark's deliberately omitted fields. **Required-field population** replaces the misleading term “field completeness”; it measures whether required sections contain text, not whether that text is supported.

## Ground-truth omission check

The corpus manifest records every intentionally absent required field or required subfield. Populating one of those fields is mechanically counted as an unsupported fill, regardless of whether the prose sounds plausible.

| Arm | Absent-source opportunities | Populated despite absence | Records with unsupported fills | Source-grounded record rate | Left unpopulated | Surfaced as violations |
|---|---:|---:|---:|---:|---:|---:|
| A — prompt only | 12 | 10 | 10 | 83.3% | 2 | 2 |
| B — template constrained | 12 | 1 | 1 | 98.3% | 11 | 11 |
| C — template + validator loop | 12 | 1 | 1 | 98.3% | 11 | 11 |

Arm A produced content for **10 of 12** required fields or subfields that were absent from the source dictation. Arm C left **11 of 12** unpopulated and surfaced **11** as rule violations.

## Operational cost and latency

The full Arm C pipeline cost **1.9×** as much as prompt-only Arm A in this run, while C cost **5.1%** more than template-only Arm B. The 1.9× comparison is the observed price of the whole constrained pipeline, not a causal estimate for grounding alone; most of the gap already appears in structured generation, and only 3 Arm C records made more than one API call.

| Arm | Median record latency | Observed maximum |
|---|---:|---|
| A — prompt only | 1703 ms | 5669 ms (`em_11`, 1 call) |
| B — template constrained | 2395 ms | 5798 ms (`em_narrative_01`, 1 call) |
| C — template + validator loop | 2163 ms | 9880 ms (`em_narrative_12`, 2 calls) |

Arm C's median happens to be lower than Arm B's, despite including retries. With 60 records and only 3 retried records, that ordering is within run-to-run API latency noise and should not be read as free retries; retry overhead is visible in the extra calls and cost.

## Paired emergency input-shape control

The same 20 synthetic emergency cases were rendered twice from identical source-fact fingerprints. The emergency schema and generation settings stayed fixed; only dictation shape changed.

| Arm | Narrative raw conformance | Fragmented raw conformance | Narrative conformant + grounded | Fragmented conformant + grounded |
|---|---:|---:|---:|---:|
| A — prompt only | 95.0% | 85.0% | 70.0% | 65.0% |
| B — template constrained | 60.0% | 70.0% | 60.0% | 70.0% |
| C — template + validator loop | 70.0% | 75.0% | 70.0% | 70.0% |

This is a null result for the input-shape hypothesis. B and C were nominally higher on fragmented raw conformance, not lower; for C the 75% versus 70% difference is one record out of 20. That record, `em_15`, passed only because its fragmented output populated an absent visit time, while `em_narrative_15` honestly left it blank. The joint metric is therefore 70% in both C conditions.

The synthetic fragmentation transformation reorders and interrupts facts but deliberately preserves them. It tests disorder without information loss, not omitted speech or ASR deletion. Within this benchmark, source omission is the mechanism the controlled cases clearly expose; word-order disruption by itself does not show a consistent effect.

The following sensitivity check excludes the six emergency cases with intentional source omissions, leaving 14 complete-source pairs:

| Arm | Complete-source narrative | Complete-source fragmented |
|---|---:|---:|
| A — prompt only | 100.0% | 92.9% |
| B — template constrained | 85.7% | 100.0% |
| C — template + validator loop | 100.0% | 100.0% |

## First-attempt pairing check

Arms B and C use the same first-attempt prompt, model snapshot, seed, and temperature. Their aggregate per-rule failure counts matched exactly, while record-level failure sets matched for **55 of 60** records and structured outputs matched for **43 of 60** records. Seeded API output is best-effort rather than bitwise deterministic, so retry benefit is measured within Arm C from its own first attempt to its final attempt.

## Arm C failure diagnosis

| Failure group | Initial instances | Recovered | Remaining | Recovery rate |
|---|---:|---:|---:|---:|
| Model extraction or formatting | 3 | 3 | 0 | 100.0% |
| Source information absent | 11 | 0 | 11 | 0.0% |

Retries repaired every observed model extraction or formatting failure and none of the source-information absences. The validator's role is therefore routing: repairable model failures go back to the model, while missing source facts go to a human.

The earlier suspicion that `EM-FMT-402` exposed a broken feedback path was incorrect. Its source dictation omitted `SpO2`; the source-aware diagnosis correctly treats that numeric-rule failure as missing information and sends it to human review rather than retrying until the model invents a value.

## Department breakdown

| Arm | Department | Records | Required-field population | First-pass rate | Raw conformance | Conformant + grounded | Median latency | Observed maximum |
|---|---|---:|---:|---:|---:|---:|---:|---|
| A — prompt only | Emergency | 40 | 100.0% | 90.0% | 90.0% | 67.5% | 1816 ms | 5669 ms (`em_11`, 1 call) |
| A — prompt only | Internal medicine | 20 | 100.0% | 100.0% | 100.0% | 100.0% | 1584 ms | 2187 ms (`im_01`, 1 call) |
| B — template constrained | Emergency | 40 | 97.5% | 65.0% | 65.0% | 65.0% | 3957 ms | 5798 ms (`em_narrative_01`, 1 call) |
| B — template constrained | Internal medicine | 20 | 100.0% | 100.0% | 100.0% | 100.0% | 1552 ms | 2345 ms (`im_02`, 1 call) |
| C — template + validator loop | Emergency | 40 | 97.5% | 67.5% | 72.5% | 70.0% | 2384 ms | 9880 ms (`em_narrative_12`, 2 calls) |
| C — template + validator loop | Internal medicine | 20 | 100.0% | 100.0% | 100.0% | 100.0% | 1614 ms | 1939 ms (`im_14`, 1 call) |

## First-attempt failures by rule

### A — prompt only · Emergency

| Rule ID | First-attempt failures |
|---|---:|
| `EM-FMT-802` | 2 |
| `EM-FMT-402` | 2 |

### A — prompt only · Internal medicine

| Rule ID | First-attempt failures |
|---|---:|
| — | 0 |

### B — template constrained · Emergency

| Rule ID | First-attempt failures |
|---|---:|
| `EM-REQ-801` | 4 |
| `EM-FMT-802` | 3 |
| `EM-REQ-301` | 2 |
| `EM-FMT-402` | 2 |
| `EM-REQ-701` | 2 |
| `EM-REQ-001` | 1 |

### B — template constrained · Internal medicine

| Rule ID | First-attempt failures |
|---|---:|
| — | 0 |

### C — template + validator loop · Emergency

| Rule ID | First-attempt failures |
|---|---:|
| `EM-REQ-801` | 4 |
| `EM-FMT-802` | 3 |
| `EM-REQ-301` | 2 |
| `EM-FMT-402` | 2 |
| `EM-REQ-701` | 2 |
| `EM-REQ-001` | 1 |

### C — template + validator loop · Internal medicine

| Rule ID | First-attempt failures |
|---|---:|
| — | 0 |

## Arm C retry distribution

| Department | Input style | 1 attempt | 2 attempts | 3 attempts |
|---|---|---:|---:|---:|
| Emergency | Fragmented | 20 | 0 | 0 |
| Emergency | Narrative | 17 | 3 | 0 |
| Internal medicine | Narrative | 20 | 0 | 0 |

## Unresolved after retry policy

| Department | Input style | Record | Attempts | Remaining rule IDs | Next action |
|---|---|---|---:|---|---|
| Emergency | Fragmented | `em_03` | 1 | `EM-REQ-801` | Human completion required |
| Emergency | Narrative | `em_narrative_03` | 1 | `EM-REQ-801` | Human completion required |
| Emergency | Fragmented | `em_06` | 1 | `EM-REQ-301` | Human completion required |
| Emergency | Narrative | `em_narrative_06` | 1 | `EM-REQ-301` | Human completion required |
| Emergency | Fragmented | `em_09` | 1 | `EM-FMT-402` | Human completion required |
| Emergency | Narrative | `em_narrative_09` | 1 | `EM-FMT-402` | Human completion required |
| Emergency | Narrative | `em_narrative_15` | 1 | `EM-REQ-001` | Human completion required |
| Emergency | Fragmented | `em_18` | 1 | `EM-REQ-801` | Human completion required |
| Emergency | Narrative | `em_narrative_18` | 1 | `EM-REQ-801` | Human completion required |
| Emergency | Fragmented | `em_20` | 1 | `EM-REQ-701` | Human completion required |
| Emergency | Narrative | `em_narrative_20` | 2 | `EM-REQ-701` | Human completion required |
