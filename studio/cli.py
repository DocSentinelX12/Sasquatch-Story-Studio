"""Studio command line entry point."""

import argparse
import json
from .ingest import ingest_story


def main() -> int:
    parser = argparse.ArgumentParser(prog="sasquatch-studio")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate-story")
    p.add_argument("--id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--kind", choices=["idea", "story", "script", "director_script"], required=True)
    p.add_argument("file")
    args = parser.parse_args()
    if args.command == "validate-story":
        with open(args.file, "r", encoding="utf-8") as handle:
            story = ingest_story(story_id=args.id, title=args.title, text=handle.read(), source_kind=args.kind)
        print(json.dumps({"id": story.id, "title": story.title, "source_kind": story.source_kind}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
