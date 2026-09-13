"""Studio command line entry point."""

import argparse
import json
from pathlib import Path

from .assets import index_assets, write_index
from .ingest import ingest_story
from .models import Story


def _story_from_file(args: argparse.Namespace) -> Story:
    text = Path(args.file).read_text(encoding="utf-8")
    return ingest_story(story_id=args.id, title=args.title, text=text, source_kind=args.kind)


def main() -> int:
    parser = argparse.ArgumentParser(prog="sasquatch-studio")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate-story")
    validate.add_argument("--id", required=True)
    validate.add_argument("--title", required=True)
    validate.add_argument("--kind", choices=["idea", "story", "script", "director_script"], required=True)
    validate.add_argument("file")

    assets = sub.add_parser("index-assets")
    assets.add_argument("root")
    assets.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "validate-story":
        story = _story_from_file(args)
        print(json.dumps({"id": story.id, "title": story.title, "source_kind": story.source_kind}, indent=2))
        return 0
    if args.command == "index-assets":
        records = index_assets(args.root)
        destination = write_index(records, args.output)
        print(json.dumps({"asset_count": len(records), "output": str(destination)}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
