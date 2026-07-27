from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "opac_survey_schema_test",
    ROOT / "scripts" / "opac_survey.py",
)
assert SPEC and SPEC.loader
opac = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = opac
SPEC.loader.exec_module(opac)


class SchemaTests(unittest.TestCase):
    def load_schema(self, schema_name: str) -> dict:
        return json.loads(
            (ROOT / "schemas" / schema_name).read_text(encoding="utf-8")
        )

    def assert_valid_data(self, schema: dict, data: dict) -> None:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(data))
        self.assertEqual(errors, [], [error.message for error in errors])

    def assert_valid(self, schema_name: str, example_name: str) -> None:
        schema = self.load_schema(schema_name)
        example = json.loads(
            (ROOT / "examples" / example_name).read_text(encoding="utf-8")
        )
        self.assert_valid_data(schema, example)

    def test_request_example_matches_schema(self) -> None:
        self.assert_valid("request.schema.json", "request.example.json")

    def test_survey_example_matches_schema(self) -> None:
        self.assert_valid("survey.schema.json", "survey.example.json")

    def test_actual_cached_collection_matches_survey_schema(self) -> None:
        config = json.loads(
            (ROOT / "examples" / "request.example.json").read_text(encoding="utf-8")
        )
        config["keywords"] = ["数据结构"]
        config["include_shelf_locations"] = False
        search_result = json.loads(
            (ROOT / "tests" / "fixtures" / "search_response.json").read_text(
                encoding="utf-8"
            )
        )

        def reject_network(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("network must not be used")

        with tempfile.TemporaryDirectory() as directory:
            cache = opac.Cache(Path(directory))
            search_key = json.dumps(
                {
                    "keyword": "数据结构",
                    "page_size": config["max_results_per_keyword"],
                },
                ensure_ascii=False,
            )
            cache.set("search", search_key, search_result)
            for marc_no in ("MARC001", "MARC002"):
                cache.set(
                    "metadata",
                    marc_no,
                    {
                        "detail_url": f"{opac.BASE}item.php?marc_no={marc_no}",
                        "fields": {"题名": f"脱敏书目 {marc_no}"},
                        "repeated_fields": {},
                    },
                )
                cache.set(
                    "holdings",
                    marc_no,
                    [
                        {
                            "call_no": "TP000/1",
                            "barcode": f"BARCODE-{marc_no}",
                            "volume": "",
                            "location": "脱敏馆藏地",
                            "status": "可借",
                        }
                    ],
                )
            client = opac.RequestClient(opener=reject_network)
            survey = opac.collect(config, cache, client)

        self.assert_valid_data(self.load_schema("survey.schema.json"), survey)

    def test_documented_request_blocks_match_schema(self) -> None:
        schema = self.load_schema("request.schema.json")
        for filename in ("README.md", "SKILL.md"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            blocks = re.findall(r"```json\n(.*?)\n```", text, flags=re.S)
            with self.subTest(filename=filename):
                self.assertEqual(len(blocks), 1)
                self.assert_valid_data(schema, json.loads(blocks[0]))

    def test_survey_schema_does_not_claim_agent_recommendation_fields(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "survey.schema.json").read_text(encoding="utf-8")
        )
        properties = schema["properties"]

        self.assertNotIn("library_top10", properties)
        self.assertNotIn("learning_value_top10", properties)
        self.assertNotIn("recommendations", properties)


if __name__ == "__main__":
    unittest.main()
