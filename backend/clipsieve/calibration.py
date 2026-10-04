"""Results writer for `rubrics/<pack>.calibration.md` (overview C.11, C.12).

`sieve eval` owns only the block between `RESULTS_START` and `RESULTS_END`: one
`### <golden stem> <mode> (<date>)` section per golden set and mode. Everything outside the
markers is hand-written and never touched.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from clipsieve.config import REPO_ROOT

RESULTS_START = "<!-- results:start -->"
RESULTS_END = "<!-- results:end -->"
_SECTION = re.compile(
    r"^### (?P<stem>\S+) (?P<mode>\w+) \((?P<date>\d{4}-\d{2}-\d{2})\)\n(?P<body>.*?)(?=^### |\Z)",
    re.S | re.M,
)


def repo_root() -> Path:
    """The checkout root; `sieve eval` puts it on `sys.path` so `evals.score` imports."""
    return REPO_ROOT


def _header(path: Path) -> str:
    name = path.name.removesuffix(".calibration.md")
    return (
        f"# {name} calibration\n\n"
        "Results written by `sieve eval`. Do not edit inside the markers.\n\n"
        f"{RESULTS_START}\n{RESULTS_END}\n"
    )


def write_results(
    calibration_path: Path, stem: str, mode: str, table_md: str, when: datetime
) -> None:
    """Replace the `### <stem> <mode> (<date>)` section between the markers.

    Other sections and all text outside the markers are kept. A missing file is created with a
    header; a file without markers gets them appended.
    """
    text = (
        calibration_path.read_text(encoding="utf-8")
        if calibration_path.exists()
        else _header(calibration_path)
    )
    if RESULTS_START not in text or RESULTS_END not in text:
        text = text.rstrip("\n") + f"\n\n{RESULTS_START}\n{RESULTS_END}\n"
    head, rest = text.split(RESULTS_START, 1)
    block, tail = rest.split(RESULTS_END, 1)
    sections = {
        (m.group("stem"), m.group("mode")): (m.group("date"), m.group("body").rstrip("\n") + "\n")
        for m in _SECTION.finditer(block)
    }
    sections[(stem, mode)] = (when.strftime("%Y-%m-%d"), table_md.rstrip("\n") + "\n")
    new_block = "\n" + "".join(
        f"### {s} {m} ({dt})\n{body}\n" for (s, m), (dt, body) in sorted(sections.items())
    )
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    calibration_path.write_text(
        f"{head}{RESULTS_START}{new_block}{RESULTS_END}{tail}", encoding="utf-8"
    )
