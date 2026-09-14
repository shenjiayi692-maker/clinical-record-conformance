# Methodology

This repository is a public, synthetic-data reconstruction of a clinical-documentation conformance pipeline. It evaluates the behavior of a constraint layer; it does not reproduce a hospital system or claim clinical validity.

## Rule provenance

The schemas represent two distinct layers:

- The public baseline cites the National Health Commission's [《病历书写基本规范》](https://www.nhc.gov.cn/yzygj/c100068/201002/766b58f0dd9242d3b62276e5c88d27dc.shtml), issued as 卫医政发〔2010〕11号. Each mapped rule names its applicable article.
- Department-specific rules use the source `illustrative departmental template (synthetic)`. Their layouts, thresholds, encodings, closed vocabularies, and ordering constraints are fictional and do not transcribe customer assets.

Every rule must have a `source`, and schema loading rejects missing or unrecognized provenance. The schemas are evaluation subsets, not complete clinical-record specifications.

## Corpus and omission ground truth

The corpus contains 20 internal-medicine narratives and 20 emergency cases rendered in two forms: ordered narrative and fragmented dictation. Each emergency pair comes from the same source-fact object and shares a SHA-256 fact fingerprint.

[`data/manifest.json`](../data/manifest.json) records each case, input style, fact fingerprint, deliberately omitted required fields, and the rule expected to surface each omission. An output that populates a controlled omission is counted as an unsupported fill, even when the value sounds plausible.

This grounding check is intentionally narrow. It detects unsupported fills only for controlled omissions; it is not a general factual-consistency evaluator for every generated phrase.

## Three arms and failure routing

- Arm A receives the prose standard and emits free text.
- Arm B receives the strict JSON template and gets one attempt.
- Arm C uses the same structured first attempt as B, then applies a source-aware validator policy.

Arm C routes required-field failures and source-absent numeric facts to human review. Only model-repairable parse, formatting, terminology, or ordering failures are returned as rule-message feedback, with at most three total attempts. Retries are stateless and do not include the previous generated record.

The deterministic validator supports `required`, length bounds, required and forbidden patterns, numeric fields, section order, and fixed timestamp format. Its role is diagnosis and routing: regeneration can repair a model failure, but it cannot recover a fact that was never present in the source.

## Metrics

- **Raw conformance:** the final output has no validator violations.
- **Required-field population:** required sections contain text. This does not imply that the text is supported or correct.
- **Source-grounded record:** no manifest-controlled omission was populated.
- **Conformant and grounded:** the record passes the validator and has no unsupported fill of a controlled omission.

Latency is reported as the median and observed maximum, not p95. Cost and Arm C latency include all attempts.

## Reproducibility

The committed [`results/final_run.jsonl`](../results/final_run.jsonl) contains one logical run: 60 records, 180 record-arm paths, and three additional Arm C attempts. Attempt keys are unique and contiguous, every record covers A/B/C, the generation configuration is constant, and timestamps are monotonic. The file is byte-identical to the single timestamped run that produced it; that run was resumed after a transient rate limit without changing configuration.

See [`results/report.md`](../results/report.md) for the complete results, failure inventory, latency, cost, and paired-control analysis.
