"""Re-render an existing synthetic report model into a new file for offline visual QA."""
import argparse
import json
from pathlib import Path
from server.analysis.report_html import render_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    model = json.loads(args.model.read_text())
    if model.get("synthetic") is not True:
        parser.error("Preview QA accepts only explicitly synthetic reports")
    document = render_report(model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(document)
    print(json.dumps({"synthetic": True, "source_model": str(args.model.resolve()), "html": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
