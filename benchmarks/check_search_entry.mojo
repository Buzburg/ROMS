"""Live Mojo entry-point smoke check against an explicitly supplied local index."""
from std.sys import argv
from std.python import PythonObject
from app_mojo.rag_engine import search_knowledge_base


def main() raises:
    var args = argv()
    if len(args) != 3:
        raise Error("Usage: check_search_entry QUERY DATABASE")
    print(search_knowledge_base(args[1], 5, PythonObject(args[2])))
