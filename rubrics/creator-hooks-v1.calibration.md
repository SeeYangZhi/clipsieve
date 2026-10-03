# creator-hooks-v1 calibration

Pack version: 1. Jev model: jev-1.13.0. Status: NOT CALIBRATED.

Filled by `sieve eval` (plan 05). Do not edit the tables by hand.

## English golden set (evals/golden/en-100.jsonl)

| question | n | agreement | mean confidence | notes |
|---|---|---|---|---|
| hook_type | | | | |
| hook_strength | | | | |
| format | | | | |
| persona_fit | | | | |
| risky_claim | | | | |
| niche_relevance | | | | |
| format_guess | | | | |

## Chinese golden set (evals/golden/zh-100.jsonl)

| mode | question | n | agreement | mean confidence |
|---|---|---|---|---|
| raw | | | | |
| translate | | | | |
| bilingual | | | | |

## Decision

language_mode: raw (default until a mode wins by at least 5 points of agreement on hook_type and hook_strength).
