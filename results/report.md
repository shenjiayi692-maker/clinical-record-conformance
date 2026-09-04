# Clinical record conformance evaluation

Source log: `results/final_run.jsonl`

## Three-arm result

| Arm | Records | Source-grounded records | Field completeness | Pass rate after arm budget | Median record latency | Observed maximum | Unsupported fills | Total estimated cost |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| A — prompt only | 60 | 83.3% | 100.0% | 93.3% | 1703 ms | 5669 ms (`em_11`, 1 call) | 10 | $0.1958 |
| B — template constrained | 60 | 98.3% | 98.3% | 76.7% | 2395 ms | 5798 ms (`em_narrative_01`, 1 call) | 1 | $0.3525 |
| C — template + validator loop | 60 | 98.3% | 98.3% | 81.7% | 2163 ms | 9880 ms (`em_narrative_12`, 2 calls) | 1 | $0.3704 |

Field completeness is measured on final outputs and is not a grounding metric. Latency is end-to-end per record; Arm C includes all validator retries. The observed maximum identifies the record and API-call count so a single API tail is not presented as a population percentile.

## Ground-truth omission check

The corpus manifest records every intentionally absent required field or required subfield. Populating one of those fields is mechanically counted as an unsupported fill, regardless of whether the prose sounds plausible.

| Arm | Absent-source opportunities | Populated despite absence | Records with unsupported fills | Source-grounded record rate | Left unpopulated | Surfaced as violations |
|---|---:|---:|---:|---:|---:|---:|
| A — prompt only | 12 | 10 | 10 | 83.3% | 2 | 2 |
| B — template constrained | 12 | 1 | 1 | 98.3% | 11 | 11 |
| C — template + validator loop | 12 | 1 | 1 | 98.3% | 11 | 11 |

Arm A produced content for **10 of 12** required fields or subfields that were absent from the source dictation. Arm C left **11 of 12** unpopulated and surfaced **11** as rule violations.

## Paired emergency input-shape control

The same 20 synthetic emergency cases were rendered twice from identical source-fact fingerprints. The emergency schema and generation settings stayed fixed; only dictation shape changed.

| Arm | Narrative conformance | Fragmented conformance | Fragmented minus narrative | Narrative source-grounded | Fragmented source-grounded |
|---|---:|---:|---:|---:|---:|
| A — prompt only | 95.0% | 85.0% | -10.0 pp | 75.0% | 75.0% |
| B — template constrained | 60.0% | 70.0% | +10.0 pp | 95.0% | 100.0% |
| C — template + validator loop | 70.0% | 75.0% | +5.0 pp | 100.0% | 95.0% |

Holding the record standard constant, this table isolates the effect of narrative versus fragmented dictation instead of conflating input shape with department schema size.

The following sensitivity check excludes the six emergency cases with intentional source omissions, leaving 14 complete-source pairs:

| Arm | Complete-source narrative | Complete-source fragmented | Fragmented minus narrative |
|---|---:|---:|---:|
| A — prompt only | 100.0% | 92.9% | -7.1 pp |
| B — template constrained | 85.7% | 100.0% | +14.3 pp |
| C — template + validator loop | 100.0% | 100.0% | +0.0 pp |

## First-attempt pairing check

Arms B and C use the same first-attempt prompt, model snapshot, seed, and temperature. Their aggregate per-rule failure counts matched exactly, while record-level failure sets matched for **55 of 60** records and structured outputs matched for **43 of 60** records. Seeded API output is best-effort rather than bitwise deterministic, so retry benefit is measured within Arm C from its own first attempt to its final attempt.

## Arm C failure diagnosis

### By operational failure class

| Failure group | Initial instances | Recovered | Remaining | Recovery rate |
|---|---:|---:|---:|---:|
| Format / terminology / order | 5 | 3 | 2 | 60.0% |
| Required information | 9 | 0 | 9 | 0.0% |

### By rule type

| Failure group | Initial instances | Recovered | Remaining | Recovery rate |
|---|---:|---:|---:|---:|
| Required pattern | 3 | 3 | 0 | 100.0% |
| Numeric fields | 2 | 0 | 2 | 0.0% |
| Required | 9 | 0 | 9 | 0.0% |

### By source-aware root cause

| Failure group | Initial instances | Recovered | Remaining | Recovery rate |
|---|---:|---:|---:|---:|
| Model extraction or formatting | 3 | 3 | 0 | 100.0% |
| Source information absent | 11 | 0 | 11 | 0.0% |

A rule's syntax does not by itself determine recoverability. For example, a `numeric_fields` failure caused by a source dictation that omits `SpO2` is a source-information absence, not a broken feedback loop. The appropriate action is to surface the gap for human completion, not regenerate until a value appears.

## Department breakdown

| Arm | Department | Records | Field completeness | First-pass rate | Pass rate after arm budget | Median latency | Observed maximum |
|---|---|---:|---:|---:|---:|---:|---|
| A — prompt only | Emergency | 40 | 100.0% | 90.0% | 90.0% | 1816 ms | 5669 ms (`em_11`, 1 call) |
| A — prompt only | Internal medicine | 20 | 100.0% | 100.0% | 100.0% | 1584 ms | 2187 ms (`im_01`, 1 call) |
| B — template constrained | Emergency | 40 | 97.5% | 65.0% | 65.0% | 3957 ms | 5798 ms (`em_narrative_01`, 1 call) |
| B — template constrained | Internal medicine | 20 | 100.0% | 100.0% | 100.0% | 1552 ms | 2345 ms (`im_02`, 1 call) |
| C — template + validator loop | Emergency | 40 | 97.5% | 67.5% | 72.5% | 2384 ms | 9880 ms (`em_narrative_12`, 2 calls) |
| C — template + validator loop | Internal medicine | 20 | 100.0% | 100.0% | 100.0% | 1614 ms | 1939 ms (`im_14`, 1 call) |

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
