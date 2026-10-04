"""Score a rubric pack's Jev answers against human golden labels, per question, in three modes.

Pure Python over the `clipsieve` judge and rubric modules: no FastAPI, no frontend, no network of
its own. `ClaudeCliTranslator` is the only external call and always runs with a subprocess timeout.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Protocol

import structlog
import yaml
from pydantic import BaseModel

from clipsieve.judge.base import Judge, JudgeFailed, cost_usd
from clipsieve.models import JudgeAnswer, Question, RubricPack

log = structlog.get_logger(__name__)

MODES = ("raw", "translate", "bilingual")
PASS_NAME = "pass_two"
DEFAULT_RUBRICS_DIR = Path("rubrics")
# Translated in `translate` mode, plus transcript[].text, ocr[].text and comments.sample[].
TRANSLATE_FIELDS = (("post", "title"), ("post", "caption"))

Label = str | int | bool


class GoldenItem(BaseModel):
    post_id: str
    state: dict
    labels: dict[str, Label]


class QuestionAgreement(BaseModel):
    question_id: str
    type: str
    n: int
    correct: int
    agreement: float
    mean_conf_correct: float | None
    mean_conf_incorrect: float | None


class EvalReport(BaseModel):
    pack: str
    mode: str
    n_items: int
    n_skipped: int = 0
    questions: list[QuestionAgreement]
    jev_input_tokens: int
    jev_cost_usd: float
    translate_cost_usd: float


class Translator(Protocol):
    def translate(self, texts: list[str]) -> tuple[list[str], float]:
        """Return (translations in the same order and count, cost in USD)."""
        ...


class IdentityTranslator:
    def translate(self, texts: list[str]) -> tuple[list[str], float]:
        return list(texts), 0.0


class ClaudeCliTranslator:
    """Translates a batch of strings to English through `claude -p` (ClaudeCliBackend flag set)."""

    SCHEMA = json.dumps(
        {
            "type": "object",
            "properties": {"translations": {"type": "array", "items": {"type": "string"}}},
            "required": ["translations"],
            "additionalProperties": False,
        }
    )
    SYSTEM_PROMPT = (
        "Translate each string in `texts` to natural English. "
        "Preserve order and count. Return only the JSON."
    )
    TASK = "Translate the strings in the JSON on stdin."

    def __init__(
        self,
        bin: str = "claude",
        max_budget_usd: float = 1.0,
        model: str = "sonnet",
        timeout_s: int = 300,
    ) -> None:
        self.bin = bin
        self.max_budget_usd = max_budget_usd
        self.model = model
        self.timeout_s = timeout_s

    def argv(self) -> list[str]:
        return [
            self.bin,
            "-p",
            "--model",
            self.model,
            "--effort",
            "low",
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
            "--system-prompt",
            self.SYSTEM_PROMPT,
            "--output-format",
            "json",
            "--json-schema",
            self.SCHEMA,
            "--max-budget-usd",
            str(self.max_budget_usd),
            self.TASK,
        ]

    def translate(self, texts: list[str]) -> tuple[list[str], float]:
        if not texts:
            return [], 0.0
        try:
            cp = subprocess.run(
                self.argv(),
                input=json.dumps({"texts": texts}, ensure_ascii=False),
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"translation timed out after {self.timeout_s}s") from e
        env = json.loads(cp.stdout or "{}")
        if env.get("is_error") or "structured_output" not in env:
            raise RuntimeError(f"translation failed: {env.get('result')}")
        out = env["structured_output"]["translations"]
        if len(out) != len(texts):
            raise RuntimeError(f"translation count mismatch {len(out)} != {len(texts)}")
        return out, float(env.get("total_cost_usd") or 0.0)


def read_golden(path: Path) -> list[GoldenItem]:
    """One `GoldenItem` per JSON line; blank lines and lines starting with `#` are skipped."""
    items: list[GoldenItem] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            items.append(GoldenItem.model_validate_json(line))
        except ValueError as e:
            raise ValueError(f"{path.name} line {i}: {e}") from e
    return items


def _first_level(answer: JudgeAnswer) -> int:
    """Lowest level index: the minimum integer legend key, else 0 (as select/scoring.py, E.3)."""
    if answer.legend:
        keys = [int(k) for k in answer.legend if str(k).lstrip("-").isdigit()]
        if keys:
            return min(keys)
    return 0


def predicted_level(answer: JudgeAnswer, levels: int) -> int:
    """1-based level of a 0-indexed Jev answer: (argmax key, else round(value)) - first + 1."""
    index: int | None = None
    if answer.probabilities:
        keyed = {int(k): p for k, p in answer.probabilities.items() if str(k).lstrip("-").isdigit()}
        if keyed:
            index = max(keyed, key=lambda k: keyed[k])
    if index is None:
        index = round(float(answer.value))
    return max(1, min(levels, index - _first_level(answer) + 1))


def is_correct(question: Question, answer: JudgeAnswer, label: Label) -> bool:
    """Choice: exact label. Score: within one level. Noul: probability on the labelled side."""
    if question.type == "choice":
        return str(answer.value) == str(label)
    if question.type == "score":
        return abs(predicted_level(answer, len(question.criteria)) - int(label)) <= 1
    if question.type == "noul":
        p = float(answer.value)
        return (p > 0.5) if bool(label) else (p < 0.5)
    raise ValueError(f"unknown question type {question.type}")


def load_zh_examples(pack_name: str, rubrics_dir: Path) -> dict:
    """`<rubrics_dir>/<pack>.zh-examples.yaml` as a dict, or {} when the sidecar is absent."""
    p = rubrics_dir / f"{pack_name}.zh-examples.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _collect_text_refs(state: dict) -> list[tuple[dict | list, str | int]]:
    """(container, key) pairs for every non-empty text field the translate mode rewrites."""
    refs: list[tuple[dict | list, str | int]] = []
    post = state.get("post") or {}
    for _, key in TRANSLATE_FIELDS:
        if isinstance(post.get(key), str) and post[key]:
            refs.append((post, key))
    for seg in state.get("transcript") or []:
        if isinstance(seg, dict) and seg.get("text"):
            refs.append((seg, "text"))
    for item in state.get("ocr") or []:
        if isinstance(item, dict) and item.get("text"):
            refs.append((item, "text"))
    sample = (state.get("comments") or {}).get("sample") or []
    for i, s in enumerate(sample):
        if isinstance(s, str) and s:
            refs.append((sample, i))
    return refs


def _with_zh_examples(pack: RubricPack, zh_examples: dict) -> RubricPack:
    """A deep copy of `pack` with each Chinese example appended to its criterion text."""
    p2 = pack.model_copy(deep=True)
    for qid, examples in zh_examples.items():
        q = p2.questions.get(qid)
        if q is None or not isinstance(examples, dict):
            continue
        if q.type == "choice":
            for label, ex in examples.items():
                if label in q.criteria:
                    q.criteria[label] = f"{q.criteria[label]} {ex}"
        elif q.type == "score":
            for level, ex in examples.items():
                idx = int(level) - 1  # sidecar levels are 1-based, criteria is a 0-based list
                if 0 <= idx < len(q.criteria):
                    q.criteria[idx] = f"{q.criteria[idx]} {ex}"
    return p2


def apply_mode(
    pack: RubricPack, item: GoldenItem, mode: str, translator: Translator, zh_examples: dict
) -> tuple[RubricPack, dict, float]:
    """(pack to judge with, state to send, translation cost) for one golden item in `mode`."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode == "raw":
        return pack, item.state, 0.0
    if mode == "translate":
        state = copy.deepcopy(item.state)
        refs = _collect_text_refs(state)
        translated, cost = translator.translate([container[key] for container, key in refs])
        for (container, key), text in zip(refs, translated, strict=True):
            container[key] = text
        return pack, state, cost
    return _with_zh_examples(pack, zh_examples), item.state, 0.0


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _confidence(question: Question, answer: JudgeAnswer) -> float | None:
    if answer.confidence is not None:
        return answer.confidence
    if question.type == "noul":
        return abs(2 * float(answer.value) - 1)
    return None


async def score_pack(
    pack: RubricPack,
    golden_path: Path,
    judge: Judge,
    mode: str = "raw",
    translator: Translator | None = None,
    rubrics_dir: Path = DEFAULT_RUBRICS_DIR,
) -> EvalReport:
    """Judge every golden item (pass two, all questions) and tally per-question agreement.

    A `JudgeFailed` item is skipped and counted in `n_skipped`; any other exception propagates.
    """
    translator = translator or IdentityTranslator()
    items = read_golden(golden_path)
    zh = load_zh_examples(pack.name, rubrics_dir) if mode == "bilingual" else {}
    per_q: dict[str, dict] = {
        qid: {"type": q.type, "n": 0, "correct": 0, "conf_ok": [], "conf_bad": []}
        for qid, q in pack.questions.items()
    }
    tokens = 0
    translate_cost = 0.0
    skipped = 0
    for item in items:
        p2, state, tcost = apply_mode(pack, item, mode, translator, zh)
        translate_cost += tcost
        try:
            result = await judge.judge(
                item.post_id, PASS_NAME, state, dict(p2.questions), p2.jev_model
            )
        except JudgeFailed as e:
            skipped += 1  # one failed post must not lose the whole eval
            log.warning("eval.item_skipped", post_id=item.post_id, error=str(e))
            continue
        tokens += result.input_tokens
        for qid, q in p2.questions.items():
            if qid not in item.labels or qid not in result.answers:
                continue
            ans = result.answers[qid]
            ok = is_correct(q, ans, item.labels[qid])
            s = per_q[qid]
            s["n"] += 1
            s["correct"] += int(ok)
            conf = _confidence(q, ans)
            if conf is not None:
                (s["conf_ok"] if ok else s["conf_bad"]).append(conf)
    questions = [
        QuestionAgreement(
            question_id=qid,
            type=s["type"],
            n=s["n"],
            correct=s["correct"],
            agreement=(s["correct"] / s["n"]) if s["n"] else 0.0,
            mean_conf_correct=_mean(s["conf_ok"]),
            mean_conf_incorrect=_mean(s["conf_bad"]),
        )
        for qid, s in per_q.items()
    ]
    report = EvalReport(
        pack=pack.name,
        mode=mode,
        n_items=len(items),
        n_skipped=skipped,
        questions=questions,
        jev_input_tokens=tokens,
        jev_cost_usd=cost_usd(tokens),
        translate_cost_usd=translate_cost,
    )
    log.info(
        "eval.done",
        pack=pack.name,
        mode=mode,
        n=len(items),
        skipped=skipped,
        cost=report.jev_cost_usd,
    )
    return report


def render_markdown(report: EvalReport) -> str:
    def f(x: float | None) -> str:
        return "-" if x is None else f"{x:.2f}"

    lines = [
        f"**Pack:** `{report.pack}`  **Mode:** `{report.mode}`  **Items:** {report.n_items}  "
        f"**Skipped:** {report.n_skipped}  **Jev cost:** ${report.jev_cost_usd:.4f}  "
        f"**Translate cost:** ${report.translate_cost_usd:.4f}",
        "",
        "| question | type | n | agreement | conf when right | conf when wrong |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for q in report.questions:
        if q.n == 0:  # nothing was scored: 0.00 would read as "always wrong"
            lines.append(f"| {q.question_id} | {q.type} | 0 | - | - | - |")
            continue
        lines.append(
            f"| {q.question_id} | {q.type} | {q.n} | {q.agreement:.2f} "
            f"| {f(q.mean_conf_correct)} | {f(q.mean_conf_incorrect)} |"
        )
    return "\n".join(lines) + "\n"
