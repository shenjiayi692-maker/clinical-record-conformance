<!-- save as docs/decisions.md; link it from README next to methodology.md -->

# Design decisions

[`methodology.md`](./methodology.md) states what this benchmark does. This document states why, what the alternative was, and what the choice cost. Five decisions mattered more than the rest.

## The validator never calls a model

An LLM judge is cheaper to write and covers rules that resist formalization.

It was rejected because a judge invents scores through the same mechanism by which a generator invents facts. Sharing a failure mode with the system under test does not weaken a benchmark at the margin — it removes the benchmark's ability to detect the one thing it exists to detect. [`src/validator.py`](../src/validator.py) therefore contains no model call at all, which is also why the published table can be recomputed from the committed run log with no API key and no network.

**Cost:** only rules expressible as required, length, pattern, numeric, ordering, or timestamp checks can be tested. Genuinely fuzzy clinical quality is outside this benchmark, and is declared outside it rather than silently approximated.

## Rule provenance is a load-time invariant, not a promise in prose

The central claim of this repository is that it contains no hospital template and no institutional rule. That claim is worth exactly as much as its weakest enforcement, and a README sentence is the weakest possible enforcement: it survives only until someone adds a rule in a hurry.

So schema loading fails — not warns — when a rule declares a `source` that is neither a citation into the public national standard nor the literal marker identifying the departmental layer as synthetic. A rule with no honest provenance cannot enter the system, because the system will not start.

**Cost:** adding a rule requires deciding where it came from before it can run. That friction is the point.

## A retry re-reads the source instead of editing the last answer

The ordinary repair loop returns the model its own output alongside the validation errors and asks for a fix. That was rejected.

With the failed record in context, the model edits around whatever it already invented. A fabricated value that happens to satisfy the rules survives the repair untouched, because nothing in the loop asks where it came from — and the repaired record then scores as a clean pass. Each attempt is therefore built fresh from the source dictation, and the only thing carried forward is the list of violated rule messages.

**Cost:** every attempt pays full input tokens again. In the committed run the three retrying records added 5.1% over Arm B.

## The loop refuses to retry what the source cannot answer

This is the decision the result rests on, and it is the one a uniform retry loop gets wrong.

A loop that retries every violation applies escalating pressure to fill a required field. When the fact is genuinely absent from the source, the only available way to relieve that pressure is to invent a plausible value. Such a loop does not merely fail to prevent fabrication — it manufactures the exact failure this benchmark exists to measure, and then reports the result as a pass.

So the partition re-reads the dictation before deciding. A violated required rule is never retried. A numeric-field violation is retried only when the number is actually present in the source. Parse, length, pattern, and ordering failures are model-repairable and go back for another attempt; when nothing is retryable the loop stops and the record goes to human review rather than to another sampling of the model.

Recovery of 3 of 3 formatting failures and 0 of 11 source-absent fields is this decision measured. The zero is not a limitation. It is the loop declining to fabricate, which is the only correct behavior available to it.

**Cost:** the partition needs a per-rule-type answer to "can the source settle this?", and that answer currently exists only for required and numeric-field rules. A new rule type needs one written before it can be trusted inside Arm C.

## The headline metric changed once, and the ranking reversed

This benchmark first measured conformance alone. Under that metric Arm A — plain prose, no structure, no validator — won clearly at 93.3%, and the conclusion would have been that the structural machinery is not worth its cost.

That conclusion was an artifact of the metric. Arm A scored well by quietly completing the fields the manifest had deliberately emptied, and because the completions were clinically plausible, a conformance check could not tell them from correct extraction. Which is the problem restated: the failure mode is invisible to the measurement most likely to be used on it.

The headline moved to a joint metric requiring a record to pass validation *and* populate no manifest-controlled omission. The ranking reversed, and the margin narrowed to under two points — a much smaller claim about a much harder question.

**Cost:** lower numbers that need a paragraph to explain. `data/manifest.json` also has to be written before generation rather than judged after it, which caps the corpus at what can be constructed by hand.
