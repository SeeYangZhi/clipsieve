"""Deterministic judge fixtures for the five fixture posts.

Run: uv run python tests/fixtures/judge/make_fixtures.py
Labels, level counts and legends come from rubrics/creator-hooks-v1.yaml, so a pack edit that
changes them fails here instead of leaving stale fixtures. Answer shapes match `from_typesafe`.
"""

import json
from pathlib import Path

from clipsieve.judge.rubric import PASS_ONE, PASS_TWO, load_pack, questions_for_pass
from clipsieve.models import ChoiceQuestion, JudgeResult, ScoreQuestion

HERE = Path(__file__).parent
PACK = load_pack(HERE.parents[3] / "rubrics" / "creator-hooks-v1.yaml")
LATENCY_MS = 310
TOKENS = {PASS_ONE: 640, PASS_TWO: 2900}

# post -> (niche_relevance, format_guess, hook_type, hook_strength, format, persona_fit,
#          risky_claim, confidence)
TABLE = {
    "local:fx-001": (3.8, "vlog_montage", "story", 3.6, "vlog_montage", 3.9, 0.05, 0.85),
    "local:fx-002": (3.2, "talking_head", "bold_claim", 2.9, "talking_head", 2.4, 0.82, 0.80),
    "local:fx-003": (0.6, "image_carousel", "result_first", 2.1, "image_carousel", 0.4, 0.03, 0.90),
    "local:fx-004": (3.9, "vlog_montage", "curiosity_gap", 3.9, "vlog_montage", 3.5, 0.08, 0.88),
    "local:fx-005": (3.4, "image_carousel", "problem", 1.6, "image_carousel", 2.8, 0.10, 0.35),
}


def choice(qid: str, value: str, conf: float) -> dict:
    q = PACK.questions[qid]
    assert isinstance(q, ChoiceQuestion) and value in q.criteria, (qid, value)
    rest = round((1 - conf) / max(1, len(q.criteria) - 1), 4)
    probs = {label: (conf if label == value else rest) for label in q.criteria}
    return {"type": "choice", "value": value, "confidence": conf, "probabilities": probs}


def score(qid: str, value: float, conf: float) -> dict:
    q = PACK.questions[qid]
    assert isinstance(q, ScoreQuestion) and 0 <= value <= len(q.criteria) - 1, (qid, value)
    lo = int(value)
    hi = min(len(q.criteria) - 1, lo + 1)
    frac = round(value - lo, 3)
    probs = {str(i): 0.0 for i in range(len(q.criteria))}
    probs[str(lo)] = round(1 - frac, 3)
    if hi != lo:
        probs[str(hi)] = frac
    legend = {str(i): text for i, text in enumerate(q.criteria)}
    return {
        "type": "score",
        "value": value,
        "confidence": conf,
        "probabilities": probs,
        "legend": legend,
    }


def noul(p: float) -> dict:
    return {"type": "noul", "value": p}


def build() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for post_id, (nr, fg, ht, hs, fm, pf, rc, conf) in TABLE.items():
        safe = post_id.replace(":", "__")
        all_answers = {
            "niche_relevance": score("niche_relevance", nr, conf),
            "format_guess": choice("format_guess", fg, conf),
            "hook_type": choice("hook_type", ht, conf),
            "hook_strength": score("hook_strength", hs, conf),
            "format": choice("format", fm, conf),
            "persona_fit": score("persona_fit", pf, conf),
            "risky_claim": noul(rc),
        }
        for pass_name in (PASS_ONE, PASS_TWO):
            ids = questions_for_pass(PACK, pass_name)
            doc = {
                "post_id": post_id,
                "pass_name": pass_name,
                "model": PACK.jev_model,
                "input_tokens": TOKENS[pass_name],
                "latency_ms": LATENCY_MS,
                "answers": {qid: all_answers[qid] for qid in ids},
            }
            assert set(all_answers) >= set(ids) and len(ids) == len(doc["answers"])
            JudgeResult.model_validate(doc)
            out[f"{safe}.{pass_name}.json"] = doc
    return out


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    docs = build()
    for name, doc in docs.items():
        (HERE / name).write_text(render(doc), encoding="utf-8")
    print("wrote", len(docs), "fixtures")
