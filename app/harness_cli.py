"""Portable command-line entry point for preparing an advisory ROMS request."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

from app.config import SKILLS_DIR
from app.harness import decode_request, prepare_request


def _read_request(path: Path) -> str:
    if not path.is_file():
        raise ValueError("The request must be a regular JSON file")
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("The request must be a regular JSON file")
        raw = stream.read(32_769)
    if len(raw) > 32_768:
        raise ValueError("The request exceeds 32 KiB")
    return raw.decode("utf-8", errors="strict")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="roms.py harness",
        description="Prepare bounded context and an advisory decision; never execute an action.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", type=Path, help="A JSON request containing goal and options")
    source.add_argument("--goal", help="Goal to review; also supply --options")
    parser.add_argument("--options", help="JSON object mapping option IDs to descriptions")
    parser.add_argument("--evidence", help="Observed facts, separate from the question")
    parser.add_argument("--skill", action="append", dest="skills", help="Selected Markdown skill name; repeat up to four times")
    parser.add_argument("--max-context-chars", type=int, help="Combined text budget, 512–16000 characters")
    parser.add_argument("--db", type=Path, help="Existing ROMS knowledge index; opened read-only")
    parser.add_argument("--skills-dir", type=Path, default=SKILLS_DIR, help="Operator-owned skill directory")
    args = parser.parse_args(argv)
    if args.request and any(value is not None for value in
                            (args.options, args.evidence, args.skills, args.max_context_chars)):
        parser.error("Put goal, options, evidence, skills and budget inside the request file")
    if args.goal is not None and args.options is None:
        parser.error("--goal requires --options; ROMS does not invent permitted actions")
    try:
        if args.request:
            request = decode_request(_read_request(args.request))
        else:
            request = {"goal": args.goal, "options": decode_request(args.options)}
            for field, value in (("evidence", args.evidence), ("skills", args.skills),
                                 ("max_context_chars", args.max_context_chars)):
                if value is not None:
                    request[field] = value
            request = decode_request(json.dumps(request, ensure_ascii=False))
        report = prepare_request(request, db_path=args.db, skills_dir=args.skills_dir)
        print(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False))
        return 0
    except (ValueError, OSError, ImportError) as error:
        print(json.dumps({"error": str(error), "execution_allowed": False}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
