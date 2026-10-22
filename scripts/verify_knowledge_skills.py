"""Verify the full source-to-skill lifecycle using real local embeddings and parsing."""
from pathlib import Path
import json
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from app.db import init_database, get_connection
    from app.okf_loader import ingest_document_file, scan_knowledge_files, prune_missing_knowledge
    from app.knowledge_skills import list_drafts, get_draft, record_feedback, render_markdown, rebuild
    from app.rag_engine import local_search
    with tempfile.TemporaryDirectory(prefix='roms-skills-') as temp:
        root = Path(temp)
        db = root/'verification.db'
        init_database(db)
        guide = root/'backup.md'
        text = '# Database backup\n\nUse only on the staging database.\n\n1. Stop the staging writer.\n2. Copy the database into a new backup file.\n3. Verify the copied database opens.\n'
        guide.write_text(text)
        assert ingest_document_file(guide, db)
        listed = list_drafts(db, 'database backup')
        assert listed['total'] == 1
        key = listed['skills'][0]['id']
        draft = get_draft(key, db)
        assert draft['variants'][0]['steps'] == 3
        assert local_search('How do I back up the database?', db_path=db)[0]['doc_id'] == 'backup.md'
        record_feedback(key, draft['revision'], 'helpful', 'Verified synthetic fixture', 'fixture-1', db)
        assert get_draft(key, db)['feedback'] == {'helpful': 1}
        extra = root/'backup-extra.md'
        extra.write_text(text + '\nCheck that no production database is selected.\n')
        assert ingest_document_file(extra, db)
        updated = get_draft(key, db)
        assert updated['procedure_variants'] == 2 and updated['source_documents'] == 2
        assert updated['revision'] != draft['revision'] and updated['feedback'] == {}
        assert 'review_status: candidate' in render_markdown(updated)
        assert rebuild(db)['source_procedures'] == 2
        for path in (guide, extra):
            path.unlink()
        files, identity = scan_knowledge_files(root)
        prune_missing_knowledge(root, files, identity, db)
        assert list_drafts(db)['total'] == 0
        get_connection(db).close()
    print(json.dumps({'status': 'passed', 'checks': ['real embedding ingestion', 'automatic cited draft',
          'hybrid document retrieval', 'additional evidence variants', 'revision-specific feedback',
          'portable Markdown', 'repeatable backfill', 'deleted source removal']}))


if __name__ == '__main__':
    main()
