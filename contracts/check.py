"""Validate PH01 contract examples, not the future analysis implementation."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

root = Path(__file__).resolve().parent
schema = json.loads((root / "schema.json").read_text())
Draft202012Validator.check_schema(schema)
examples = json.loads((root / "examples.json").read_text())
for case in examples:
    selected = {**schema, "$ref": "#/$defs/" + case["definition"]}
    errors = list(Draft202012Validator(selected, format_checker=FormatChecker()).iter_errors(case["data"]))
    assert (not errors) == case["valid"], (case["id"], [e.message for e in errors])
    print("PASS", case["id"])
print(f"{len(examples)} contract examples passed")

v3_schema = json.loads((root / "casual_game_v3.schema.json").read_text())
Draft202012Validator.check_schema(v3_schema)
v3_examples = json.loads((root / "casual_game_v3_examples.json").read_text())
for case in v3_examples:
    selected = {**v3_schema, "$ref": "#/$defs/" + case["definition"]}
    errors = list(Draft202012Validator(selected, format_checker=FormatChecker()).iter_errors(case["data"]))
    assert (not errors) == case["valid"], (case["id"], [e.message for e in errors])
    print("PASS", case["id"])
print(f"{len(v3_examples)} Candidate V3 contract examples passed")
