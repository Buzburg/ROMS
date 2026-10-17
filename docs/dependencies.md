# What ROMS actually depends on

Design inspiration does not create a package dependency. ROMS does not install
or query the reference search/research repositories. Their old search clients and
comparison runners have been removed. One embedded local search engine serves
the application.

The remaining packages have concrete runtime uses:

| Capability | Actual dependency | Where it is used |
|---|---|---|
| Compiled search and text kernels | Mojo compiler at build time; compiled extension at runtime | `app_mojo/search_kernels.mojo`, `app_mojo/document_text.mojo`, `app/search_native.py` |
| MCP tools and client protocol | FastMCP; the base MCP SDK | `app/server.py`, `app/broker_memory.py` |
| Local semantic embeddings | SentenceTransformers and its model/tokenizer runtime, including PyTorch | `app/config.py`, `app/okf_loader.py` |
| Vector storage and numeric conversion | sqlite-vec, NumPy; Python's SQLite module for FTS5 | `app/db.py`, `app/rag_engine.py` |
| Markdown metadata and recovery | python-frontmatter and its YAML parser dependency | `app/document_parse.py`, `app/tools.py` |
| PDF/Office/image text extraction | pypdf, Pillow, python-docx, python-pptx, openpyxl | `app/document_extract.py` |
| Printed text in images and scans | Local Tesseract with English data; Poppler for PDF rendering | `app/document_extract.py` |
| Resource limits and metrics | psutil | `app/throttle.py`, `app/tools.py` |
| Optional HTTP gateway and model-service integrations | HTTPX, Starlette, Uvicorn | `app/gateway.py`, project/model clients |

The gateway packages remain in the full server requirements because the download
includes those entry points. No gateway process or external model service is
started just by installing them. Optional workshop commands can invoke separately
configured tools; those tools are not dependencies of local knowledge search and
are not installed by `requirements.txt`.

The CPU switch removes 16 NVIDIA/CUDA/Triton packages from the previous Pixi
lockfile. The resolved default environment contains no pytest; the development
environment includes it. Package compatibility, all 112 focused search/intake
tests and six real-model integration tests were checked in a fresh Python
environment.

## Runtime versus development

- `requirements.txt` installs the application runtime. Linux/Windows resolve the
  tested CPU-only PyTorch 2.14.1 build rather than the default CUDA distribution.
  Pixi uses the same CPU package source. The unused MCP command-line
  extra has been removed; the base SDK stays because ROMS imports it.
- `requirements-dev.txt` adds pytest for development and verification. pytest is
  no longer part of the runtime requirements.
- `requirements-ci.txt` is the lightweight portable-test environment; it does not
  install the embedding model or document extraction stack.
- Pixi's `dev` environment adds pytest. Use `pixi run -e dev test-search` to run
  native search tests; ordinary build/server tasks use the default environment.

Pydantic is no longer declared directly because ROMS does not import it. FastMCP
and other installed packages still depend on it, so this is a declaration cleanup,
not a claim that Pydantic disappears from the resolved environment. Similarly,
removing an unused install extra does not guarantee a smaller resolved install if
another genuine dependency requests the same underlying package.

PDF/Office/OCR libraries and the embedding runtime are not inspiration credits:
ROMS calls them. Removing them without replacing their implementations would
remove requested features. Source provenance and notices for actual bundled code
remain separate from the dependency list; a design reference alone requires no
runtime adapter, installed checkout or blanket attribution claim.
