#!/usr/bin/env python3
"""Validate repository examples against their JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ("request", ROOT / "schemas/request.schema.json", ROOT / "examples/request.example.json"),
    ("survey", ROOT / "schemas/survey.schema.json", ROOT / "examples/survey.example.json"),
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    for name, schema_path, example_path in PAIRS:
        schema = load_json(schema_path)
        example = load_json(example_path)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(example), key=lambda error: list(error.path))
        if errors:
            for error in errors:
                location = ".".join(str(part) for part in error.path) or "<root>"
                print(f"{name}: {location}: {error.message}")
            return 1
        print(f"{name}: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
