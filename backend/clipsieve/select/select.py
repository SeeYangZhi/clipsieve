"""Selection output model. Plan 03 adds select(), pass_one_keep() and helpers to this module."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shortlist: list[str]
    review: list[str]
    scores: dict[str, float]
    dropped: dict[str, str]
