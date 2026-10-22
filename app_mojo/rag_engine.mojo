"""One local search entry point shared with Python/MCP.

Native typo expansion and rank fusion live in search_kernels.mojo. SQLite and
EmbeddingGemma Q8 access is delegated through the shared Python adapters so
filtering, model identity, citations and cache invalidation cannot diverge.
"""
from std.python import Python, PythonObject


def search_knowledge_base(query: String, limit: Int = 3,
                          custom_db_path: PythonObject = Python.none()) raises -> String:
    var kernels = Python.import_module("app.search_native")
    if String(py=kernels.kernel_name()) != "mojo":
        raise Error("Build the Mojo search extension before using the native entry point")
    var search = Python.import_module("app.rag_engine")
    return String(py=search.search_knowledge_base(query, limit, custom_db_path))
