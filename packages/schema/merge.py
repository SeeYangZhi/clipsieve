"""Fold the per-file schemas into one root schema with a flat $defs table.

Both generators consume the merged form so that shared types (Brief, Counters, ...)
are emitted exactly once in each language.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMAS_DIR = Path(__file__).parent / "schemas"
_REF_FILE_DEF = re.compile(r"^(?P<file>[a-z_]+\.json)?#/\$defs/(?P<name>[A-Za-z0-9_]+)$")
_REF_FILE_ROOT = re.compile(r"^(?P<file>[a-z_]+\.json)$")


def _rewrite_refs(node: Any, title_by_file: dict[str, str]) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                m = _REF_FILE_DEF.match(value)
                if m:
                    out[key] = f"#/$defs/{m.group('name')}"
                    continue
                m = _REF_FILE_ROOT.match(value)
                if m:
                    out[key] = f"#/$defs/{title_by_file[m.group('file')]}"
                    continue
                raise ValueError(f"unsupported $ref: {value}")
            else:
                out[key] = _rewrite_refs(value, title_by_file)
        return out
    if isinstance(node, list):
        return [_rewrite_refs(v, title_by_file) for v in node]
    return node


def merge(schemas_dir: Path = SCHEMAS_DIR) -> dict[str, Any]:
    files = sorted(p for p in schemas_dir.glob("*.json"))
    raw = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in files}
    title_by_file = {name: doc["title"] for name, doc in raw.items()}

    defs: dict[str, Any] = {}
    root_props: dict[str, Any] = {}
    for name, doc in raw.items():
        for def_name, def_schema in doc.get("$defs", {}).items():
            if def_name in defs:
                raise ValueError(f"duplicate $def {def_name} in {name}")
            defs[def_name] = def_schema
        if name == "common.json":
            continue
        top = {k: v for k, v in doc.items() if k not in {"$schema", "$id", "$defs"}}
        defs[doc["title"]] = top
        root_props[_snake(doc["title"])] = {"$ref": f"#/$defs/{doc['title']}"}

    merged = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://clipsieve.dev/schema/clipsieve.json",
        "title": "ClipsieveSchemas",
        "type": "object",
        "additionalProperties": False,
        "properties": root_props,
        "$defs": defs,
    }
    return _rewrite_refs(merged, title_by_file)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


if __name__ == "__main__":
    print(json.dumps(merge(), indent=2, ensure_ascii=False))
