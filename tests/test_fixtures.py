import csv
import hashlib
import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from scripts.generate_fixture import generate

HAND = Path(__file__).parent / "fixtures" / "hand"

def test_hand_inventory_and_schema():
    schema = json.loads(Path("contracts/schema.json").read_text())
    users = json.loads((HAND/"users.json").read_text())
    events = json.loads((HAND/"events.json").read_text())
    expected = json.loads((HAND/"expected.json").read_text())
    assert len(users) == expected["input_users"] == 6
    assert len(events) == expected["input_events"] == 17
    assert len({e["event_id"] for e in events}) == expected["unique_events"] == 16
    for definition, rows in [("user",users),("event",events)]:
        validator = Draft202012Validator({**schema,"$ref":"#/$defs/"+definition},
                                         format_checker=FormatChecker())
        for row in rows:
            validator.validate(row)
    assert not any(e["user_id"] == "u2" for e in events)
    assert len(json.loads((HAND/"edge_cases.json").read_text())) == 6

def test_generator_reproducible_and_exclusive(tmp_path):
    left = generate(tmp_path/"a",20,200,42)
    right = generate(tmp_path/"b",20,200,42)
    for file in left.iterdir():
        assert hashlib.sha256(file.read_bytes()).digest() == hashlib.sha256(
            (right/file.name).read_bytes()).digest()
    with pytest.raises(FileExistsError):
        generate(left,20,200)
    with (left/"events.csv").open() as stream:
        assert len(list(csv.DictReader(stream))) == 200
    with (left/"users.csv").open() as stream:
        assert len(list(csv.DictReader(stream))) == 20
    assert json.loads((left/"export.json").read_text())["synthetic"] is True

def test_generator_rejects_bad_counts(tmp_path):
    with pytest.raises(ValueError):
        generate(tmp_path/"bad",0,10)
    assert not (tmp_path/"bad").exists()
