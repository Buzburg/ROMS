"""Exercise upgraded retrieval with real pinned CPU embeddings and a temporary DB."""
import json
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.db import init_database, get_connection
    from app.embedding_space import identity
    from app.okf_loader import ingest_document_file
    from app.rag_engine import local_search
    from app.source_context import expand
    from app.tool_rag import register_tool, search_tools
    from app.prompt_builder import format_context_for_local_llm, estimate_tokens
    with tempfile.TemporaryDirectory(prefix='roms-upgrade-check-') as temporary, ExitStack() as resources:
        root = Path(temporary)
        database = root / 'knowledge.db'
        init_database(database)
        resources.callback(get_connection(database).close)
        register_tool('reset_password', 'Reset a user password', 'accounts', db_path=database)
        register_tool('forecast_weather', 'Forecast rain and temperature', 'weather', db_path=database)
        query = 'recover login access'
        lexical = search_tools(query, db_path=database, semantic=False)
        semantic = search_tools(query, db_path=database)
        assert not lexical
        assert semantic and semantic[0]['tool_name'] == 'reset_password', semantic
        assert not search_tools(query, category='missing', db_path=database)
        path = root / 'pump.md'
        path.write_text('# Zephyr pump\n\n## Emergency stop\nTurn the amber lever clockwise.\n\n## Restart\nCheck the pressure gauge first.\n')
        assert ingest_document_file(path, database)
        hits = local_search('Zephyr pump emergency stop amber lever', db_path=database)
        evidence = next(hit for hit in hits if 'amber lever' in hit['content'])
        assert evidence['source']['section_path'] == ['Zephyr pump', 'Emergency stop']
        expanded = expand(evidence['chunk_id'], db_path=database)
        assert all(item['source']['section_path'] == evidence['source']['section_path'] for item in expanded['sources'])
        context = format_context_for_local_llm(hits, max_tokens=100)
        assert context and estimate_tokens(context) <= 100
        print(json.dumps({'model_identity': json.loads(identity()), 'lexical_tool_matches': len(lexical),
                          'semantic_top_tool': semantic[0]['tool_name'],
                          'semantic_similarity': semantic[0]['semantic_similarity'],
                          'source_location': evidence['source'], 'context_estimated_tokens': estimate_tokens(context),
                          'result': 'PASS'}, indent=2))


if __name__ == '__main__':
    main()
