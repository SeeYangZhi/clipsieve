"""Judge fake that replays JudgeResult fixtures by post id and pass."""

from __future__ import annotations

import json
from pathlib import Path

from clipsieve.judge.base import Judge
from clipsieve.models import JudgeResult, Question
from clipsieve.store.paths import safe_post_filename


class FixtureMissing(FileNotFoundError):
    pass


class RecordedJudge(Judge):
    """Reads `<fixture_dir>/judge/<safe post id>.<pass_name>.json`."""

    def __init__(self, fixture_dir: Path) -> None:
        self._dir = Path(fixture_dir) / "judge"
        self.calls: list[tuple[str, str]] = []

    async def judge(
        self,
        post_id: str,
        pass_name: str,
        state: dict,
        questions: dict[str, Question],
        model: str,
    ) -> JudgeResult:
        self.calls.append((post_id, pass_name))
        path = self._dir / f"{safe_post_filename(post_id)}.{pass_name}.json"
        if not path.exists():
            raise FixtureMissing(str(path))
        result = JudgeResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
        # Only the questions asked are returned, so a pack with fewer questions still works.
        answers = {qid: a for qid, a in result.answers.items() if not questions or qid in questions}
        return result.model_copy(update={"answers": answers})
