# Clinical record conformance evaluation

Source log: `results/final_run.jsonl`

## Three-arm result

| Arm | Records | Field completeness | First-pass rate | Pass rate after arm budget | Mean record latency | p95 record latency | Total estimated cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| A — prompt only | 40 | 100.0% | 75.0% | 75.0% | 5381 ms | 21911 ms | $0.1246 |
| B — template constrained | 40 | 98.6% | 85.0% | 85.0% | 6046 ms | 22016 ms | $0.2268 |
| C — template + validator loop | 40 | 98.9% | 85.0% | 87.5% | 5576 ms | 22387 ms | $0.2950 |

Field completeness is measured on each arm's final output. Latency is end-to-end per record: for arm C it includes every retry. Cost is estimated from the token rates recorded with each attempt.

## Department breakdown

| Arm | Department | Records | Field completeness | First-pass rate | Pass rate after arm budget | Mean record latency | p95 record latency |
|---|---|---:|---:|---:|---:|---:|---:|
| A — prompt only | Emergency | 20 | 100.0% | 50.0% | 50.0% | 1826 ms | 2204 ms |
| A — prompt only | Internal medicine | 20 | 100.0% | 100.0% | 100.0% | 8937 ms | 22105 ms |
| B — template constrained | Emergency | 20 | 97.2% | 70.0% | 70.0% | 2183 ms | 2723 ms |
| B — template constrained | Internal medicine | 20 | 100.0% | 100.0% | 100.0% | 9908 ms | 22137 ms |
| C — template + validator loop | Emergency | 20 | 97.8% | 70.0% | 75.0% | 3241 ms | 6121 ms |
| C — template + validator loop | Internal medicine | 20 | 100.0% | 100.0% | 100.0% | 7911 ms | 22558 ms |

## First-attempt failures by rule

### A — prompt only · Emergency

| Rule ID | First-attempt failures |
|---|---:|
| `EM-FMT-802` | 10 |
| `EM-FMT-402` | 1 |

### A — prompt only · Internal medicine

| Rule ID | First-attempt failures |
|---|---:|
| — | 0 |

### B — template constrained · Emergency

| Rule ID | First-attempt failures |
|---|---:|
| `EM-REQ-801` | 2 |
| `EM-REQ-301` | 1 |
| `EM-FMT-402` | 1 |
| `EM-REQ-001` | 1 |
| `EM-REQ-701` | 1 |

### B — template constrained · Internal medicine

| Rule ID | First-attempt failures |
|---|---:|
| — | 0 |

### C — template + validator loop · Emergency

| Rule ID | First-attempt failures |
|---|---:|
| `EM-REQ-801` | 2 |
| `EM-REQ-301` | 1 |
| `EM-FMT-402` | 1 |
| `EM-REQ-001` | 1 |
| `EM-REQ-701` | 1 |

### C — template + validator loop · Internal medicine

| Rule ID | First-attempt failures |
|---|---:|
| — | 0 |

## Arm C retry distribution

| Department | 1 attempt | 2 attempts | 3 attempts |
|---|---:|---:|---:|
| Emergency | 14 | 1 | 5 |
| Internal medicine | 20 | 0 | 0 |

## Unrecoverable after three attempts

| Department | Record | Remaining rule IDs |
|---|---|---|
| Emergency | `em_03` | `EM-REQ-801` |
| Emergency | `em_06` | `EM-REQ-301` |
| Emergency | `em_09` | `EM-FMT-402` |
| Emergency | `em_15` | `EM-REQ-001` |
| Emergency | `em_18` | `EM-REQ-801` |
