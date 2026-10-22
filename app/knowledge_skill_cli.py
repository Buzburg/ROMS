"""Local generated-skill discovery, feedback and Markdown export."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    from app import knowledge_skills as engine
    parser = argparse.ArgumentParser(description='Discover source-backed skill drafts; never installs or executes them')
    parser.add_argument('--db', type=Path, help='Existing ROMS knowledge database')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('refresh')
    listing = commands.add_parser('list')
    listing.add_argument('--query', default='')
    listing.add_argument('--offset', type=int, default=0)
    for command in ('show', 'export'):
        sub = commands.add_parser(command)
        sub.add_argument('skill_id')
        if command == 'export':
            sub.add_argument('--revision', required=True)
            sub.add_argument('--output', required=True, type=Path, help='New Markdown file; existing files are never overwritten')
    feedback = commands.add_parser('feedback')
    feedback.add_argument('skill_id')
    feedback.add_argument('--revision', required=True)
    feedback.add_argument('--outcome', required=True, choices=['helpful', 'needs_work'])
    feedback.add_argument('--event-id', required=True)
    feedback.add_argument('--note', default='')
    args = parser.parse_args(argv)
    try:
        if args.command == 'refresh':
            result = engine.rebuild(args.db)
        elif args.command == 'list':
            result = engine.list_drafts(args.db, args.query, args.offset)
        elif args.command == 'feedback':
            result = engine.record_feedback(args.skill_id, args.revision, args.outcome, args.note, args.event_id, args.db)
        else:
            result = engine.get_draft(args.skill_id, args.db)
            if not result:
                raise ValueError('No current skill found')
            if args.command == 'export':
                if result['revision'] != args.revision:
                    raise ValueError('Skill changed; review the current revision before export')
                with args.output.open('x', encoding='utf-8') as target:
                    target.write(engine.render_markdown(result))
                result = {'exported': str(args.output), 'revision': args.revision, 'status': 'candidate'}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + '\n')
