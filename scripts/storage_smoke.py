"""Explicitly authorized synthetic write/read smoke test against a configured existing bucket."""
import argparse
import json

from server.storage import S3Storage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-synthetic", action="store_true",
                        help="Authorize writing and retaining one uniquely named synthetic object")
    args = parser.parse_args()
    if not args.write_synthetic:
        parser.error("Explicit --write-synthetic required; confirm the configured bucket first")
    storage = S3Storage.from_environment()
    content = b'{"synthetic":true,"purpose":"AC Event Agent storage verification"}\n'
    manifest = storage.put_bytes(storage.new_key("verification/synthetic", "json"), content,
                                 "application/json")
    head = storage.head(manifest.object_key)
    assert head["size_bytes"] == len(content)
    assert storage.get_bytes(manifest) == content
    print(json.dumps({"status": "passed", "synthetic": True, "retained_object": manifest.to_dict(),
                      "limitations": ["CORS not tested", "restart not tested", "multipart not tested"]}, indent=2))


if __name__ == "__main__":
    main()
