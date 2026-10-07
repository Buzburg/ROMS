# ROMS component map

ROMS is a general-purpose agent harness organized around a Decision Maker, RAG, OKF, MCP and Skills. The preparation layer combines these inputs into a reviewable proposal. Supporting modules provide project memory, diagnostics and optional execution integrations.

“Implemented” means the referenced code provides the described operation. It does not mean every environment or workload has been tested. Linked reports record their own dates, fixtures, dependencies and limitations; some describe older revisions. The portable Python path has Windows and Linux checks. macOS remains unverified.

## Preparation and the five parts

[`app/harness.py`](../app/harness.py) accepts a goal, supplied options, evidence, selected skills and a context budget. It reads keyword matches from the existing knowledge index and safe Markdown skill files, invokes the existing Decision Maker without saving topic-discovery records, and returns source hashes, bounded context, an advisory decision and a proposed next step. Its contract is described in [HARNESS.md](HARNESS.md).

The six stages are **request → knowledge and skills → decision → proposal → approval → execution**. Preparation implements the first four. Approval and effects remain with the caller or a separately configured workshop. The response always requires approval and disallows execution; it does not invoke a model, network service, tool or document edit. SQLite can use normal coordination sidecars.

| Part | Implementation | What exists | Boundary |
| --- | --- | --- | --- |
| Decision Maker | [`app/decisions.py`](../app/decisions.py) | Structured option selection, yes/no and rubric scoring; thresholds can produce abstention. | The current scorer uses word features, hashed vectors and a small synthetic recurrent accumulator. It does not load trained model weights. Its `lexical_heuristic` backend scores are not empirically calibrated probabilities of correctness; a yes/no result is not factual verification. |
| RAG | [`app/rag_engine.py`](../app/rag_engine.py), [`app/prompt_builder.py`](../app/prompt_builder.py), [`app/db.py`](../app/db.py) | SQLite keyword search and `sqlite-vec` vector search, rank fusion, caching and bounded context formatting. The preparation path uses keyword retrieval from an existing index. | Passages are retrieved evidence, not verified answers. Vector indexes expect 384-dimensional embeddings. Changing providers or model weights requires a compatible rebuilt document index; updating a cache key is not reindexing. |
| OKF | [`app/okf_loader.py`](../app/okf_loader.py), [`app/source_library.py`](../app/source_library.py) | Document metadata, chunking and indexing for Markdown, CSV/TSV, JSON/JSONL, plain text and selected source formats. Knowledge ingestion keeps vector and keyword entries together. | This is the repository's knowledge-file convention and loader, not certification against an external format standard. It does not add general PDF or Office-document extraction. |
| MCP | [`app/server.py`](../app/server.py), [`app/memory_tools.py`](../app/memory_tools.py), [`app/mojo_bridge.py`](../app/mojo_bridge.py) | Registered tools, resources and prompts over local stdio. `roms_prepare_harness` exposes preparation using the server's configured database and skills root. The Python entry point is `python roms.py mcp`. | Some registered tools write data or load code. MCP transport does not supply approval or isolation. Check the particular interfaces advertised by the Python or native server you launch. |
| Skills | [`app/tools.py`](../app/tools.py), [`app/trajectory_recorder.py`](../app/trajectory_recorder.py), [`skills/`](../skills/) | Markdown playbooks can be listed, authored and read through `skills://{skill_name}`. Trajectory distillation creates inactive drafts. | Instructions do not grant permissions or prove expertise. The role catalog is separate from the server's directly readable skill files; its entry count is not a count of verified agents. |

The decision module's topic discovery uses local word statistics and hashed-vector clustering. Its legacy interface name is `roms_bertopic_discover`; that name does not mean the external BERTopic package or a trained topic model runs on this path. The decision accumulator is also separate from actual model state described below.

## Project memory and coding utilities

| Capability | Implementation | What to rely on | What not to infer |
| --- | --- | --- | --- |
| Project lessons | [`app/memory.py`](../app/memory.py), [`app/memory_context.py`](../app/memory_context.py) | Scoped lesson records, candidate/verified lifecycle, correction, retraction, expiry and source-bearing context. [Guide](local-memory.md). | “Verified” records contain evidence supplied by a caller. These functions do not execute the recorded command, authenticate a receipt or isolate mutually untrusted clients. |
| Context selection | [`app/context_select.py`](../app/context_select.py), [`app_mojo/context_select.mojo`](../app_mojo/context_select.mojo) | Bounded selection of whole records, omission reporting and an attempt to reserve a relevant failure warning. [Implementation and measurements](native-context.md). | Selection utility is a ranking heuristic, not a truth score. A character budget is not the model's token budget. Small candidate pools need not benefit from native execution. |
| Log compaction | `ContextSieve` in [`app/prefrontal_cortex.py`](../app/prefrontal_cortex.py) | Selects diagnostic source lines. The isolated first-run demo verifies that its real exception survives. | Selected-line limits and displayed omission markers differ. One fixture does not establish universal compression or preservation of every relevant line. Keep original logs. |
| Symbol lookup | `PolyglotSymdex` in [`app/prefrontal_cortex.py`](../app/prefrontal_cortex.py) | Pattern-based source symbol indexing and lookup. | The basic CLI path is not a complete parser or a guarantee of index freshness. The workshop's separate bounded adapter uses Python AST parsing where supported; other languages remain heuristic. |
| File recovery | `WorkspaceTimeMachine` in [`app/prefrontal_cortex.py`](../app/prefrontal_cortex.py) | Stores file blobs and a manifest, then writes matching saved files back. The demo verifies one controlled single-file recovery. | This is not transactional multi-file rollback, safe merging of concurrent edits or validation of an untrusted snapshot store. The basic restore writes files directly. |
| Action forecasting | `ExecutionShield` in [`app/prefrontal_cortex.py`](../app/prefrontal_cortex.py) | Flags configured command patterns and repeated actions; offers limited JSON repair. | A returned `ALLOW` or score is advisory. Pattern matching is not a security boundary, proof of safety or authorization to execute. |
| Associative memory | `HybridNeuralMemory` in [`app/prefrontal_cortex.py`](../app/prefrontal_cortex.py) | Stores key/value records with a local numerical representation. | Architecture-inspired names do not establish that a trained language model learns from these records. Use the separate lesson store when source and verification history matter. |

The [first-run demo](first-run-demo.md) verifies log selection, symbol lookup and recovery on a temporary invoice fixture. It does not test the complete harness, a live model, GPU placement or arbitrary workspace safety.

## Optional runtime and workshop components

| Area | Source and guide | Current scope |
| --- | --- | --- |
| Model gateway | [`app/gateway.py`](../app/gateway.py), [chat data handling](chat-privacy.md) | Adds retrieved context and selected instructions while forwarding requests to a separately configured model service. Local binding and authentication do not provide multi-tenant isolation. Automatic chat trajectory recording is opt-in. |
| Project workshop | [`app/project_assistant.py`](../app/project_assistant.py), [`app/patch_tasks.py`](../app/patch_tasks.py), [`app/patch_promotion.py`](../app/patch_promotion.py), [workshop verification](project-assistant-verification.md) | Stages bounded model-proposed changes, runs registered validation and requires existing operator approval for promotion. This is a separately configured Linux integration, not an effect of a positive decision score. |
| Validation workers | [`app/task_worker.py`](../app/task_worker.py), [`app/task_worker_client.py`](../app/task_worker_client.py), [worker boundary](task-worker-verification.md) | Configured local container images and native confinement support a limited validation catalog. The generic process runner alone is process separation, not proof of confinement. Arbitrary container execution is disabled by default. |
| Broker and local inference | [`app/broker_protocol.py`](../app/broker_protocol.py), [`app/native_chat.py`](../app/native_chat.py), [broker guide](omarchy-broker.md) | Additional Linux/Omarchy request, lifecycle and model-service integration. Requires documented binaries, configuration and model files. Installing the Python MCP server does not install this environment. |
| Recurrent checkpoints | [`app/workbench/`](../app/workbench/), [`native/`](../native/), [checkpoint contract](repository-integrations.md#real-recurrent-checkpoints) | A separate operator API uses actual serialized state from the pinned model backend, authenticated storage and compatibility checks. Documented tests cover greedy continuation and independent forks. It does not snapshot the installed chat service automatically; stochastic sampling and state fusion are unsupported. |
| Native kernels | [`app_mojo/`](../app_mojo/), [`pixi.toml`](../pixi.toml) | Linux/WSL Mojo sources and selected Python bindings. Context selection has documented parity checks and scoped timings. Compilation and runtime availability must be checked for the chosen component. |
| Build and review integrations | [`app/workbench/`](../app/workbench/), [integration guide](repository-integrations.md) | Operator-selected build manifests, diagnostics, advisory code review, evidence receipts and workflow rehearsal. External tools have explicit installation paths. Results do not grant patch or OS-change permission. |

Integration names, pinned dependency details and original attribution remain in implementation guides and license files. This overview does not rename or remove those dependencies.

## Experiments needing separate evaluation

- **Endpoint routing:** [`app/dual_brain_router.py`](../app/dual_brain_router.py) selects an endpoint and checks availability. Its `dispatch` method returns routing metadata; it does not itself submit a completion request. Confidence constants are not measured success probabilities.
- **Reasoning helpers:** [`app/dark_reasoner.py`](../app/dark_reasoner.py) matches supplied premises and rules using text heuristics. It is not a formal proof engine or a verified reasoning model.
- **Dataset preparation:** [`app/dream_cycle.py`](../app/dream_cycle.py) exports lessons and optional sample material to JSONL. It does not run fine-tuning, update weights or demonstrate improved answers. Empty input can produce a labelled synthetic baseline record.
- **Prompt and inventory helpers:** [`app/autokarpathy.py`](../app/autokarpathy.py) prepares prompt drafts and reports stored counts. Legacy reduction and health fields now return `null` with `evaluation_status: "not_evaluated"`; exact character counts and caller-recorded success rates are labelled separately. Existing tool identifiers remain compatible, but clients must handle these previously unsupported metrics as unmeasured.
- **Vector and code-index experiments:** [`app/vsa_tsl_engine.py`](../app/vsa_tsl_engine.py) and [`app/holographic_indexer.py`](../app/holographic_indexer.py) implement binary representations, parsing and lookup experiments. Microbenchmarks do not establish semantic relevance or general model-memory savings.
- **Error correction:** [`app/ecc_codec.py`](../app/ecc_codec.py) contains coding primitives. Their presence does not demonstrate end-to-end recovery of a damaged production knowledge store.
- **Role catalog:** [`app/role_registry.py`](../app/role_registry.py) loads descriptions and prepares prompts. A listed role is not an independently trained, tested or executing agent.

## Reading the evidence

| Evidence | What it measures | Outside its scope |
| --- | --- | --- |
| [First-run demo](first-run-demo.md) | A process failure, retained error context, source location, restored bytes and passing rerun on a temporary fixture. | Autonomous repair and concurrent edits. |
| [Retrieval report](retrieval-performance.md) | Targeted lexical/cache regressions and synthetic fusion-stage timings. | Representative relevance, end-to-end inference and answer quality. |
| [Native context report](native-context.md) | Python/native packing parity and timings on recorded synthetic inputs. | General agent speed, repair success or GPU performance. |
| [Runtime integration report](repository-integrations.md) | Named operator workflows, bounded validation, checkpoint tests and small model fixtures in the recorded environment. | Qualification of the planned Ryzen AI Max+ 395 / 128 GB machine or a complete native desktop release. |

Use the revision, fixtures and environment recorded by a report when reproducing it. Historical results can be useful without becoming a promise about a new checkout or machine. See [README verification](../README.md#verification) for portable starting checks and [SECURITY.md](../SECURITY.md) for the trust boundary.
