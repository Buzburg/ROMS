# A first useful run: recover a broken invoice calculation

An agent makes an edit. A check fails inside a noisy log. Before asking another model to guess what happened, you need the error, the relevant code location, and a verified way back to the original file.

ROMS's first-run demo exercises that sequence with existing Python tools. It generates a small, disposable invoice program; the program and its failure are deliberately simple so you can inspect every step.

## Run it

From the repository root, with Python 3.11 or newer:

```bash
python -I -S -B scripts/demo_first_run.py
```

Python's `-I -S` options keep the demonstration independent of installed third-party packages and user Python configuration. No model or package downloads are performed. It works from another directory if you supply the script's absolute path.

The script accepts only `--json` and `--help`. It does not accept a project directory, run a model, or contact a service. The temporary workspace and ROMS state are removed before success is reported. Existing ROMS data directories are not used.

## What really happens

1. Create `invoice.py` in a new temporary directory. Run it in a separate Python process and check that the total is **1550 cents**.
2. Call `WorkspaceTimeMachine.snapshot` with an explicit temporary state directory.
3. Change the fixture's calculation so it drops the 50-cent delivery charge. Run it again and require the real process to fail with **1500 cents**.
4. Pass the complete captured output to `ContextSieve.compact`. Require the actual exception and `invoice.py` file pointer to survive. Its 12-line budget counts selected source lines; omission markers are additional display lines.
5. Call `PolyglotSymdex.index_workspace` and `lookup` to find `invoice_total_cents` at `invoice.py:1`.
6. Call `WorkspaceTimeMachine.rewind`, compare the restored bytes against the original, and run the invoice check again. A success flag alone is not sufficient.
7. Remove the temporary workspace and state. Print success only after all checks and cleanup finish.

On the checked fixture, the failure log contains 204 lines and the compacted output contains 12 selected source lines plus one omission marker. Python versions can format tracebacks differently; the script reports actual counts and tests the essential error content rather than requiring a fixed line count.

## Inspect the evidence

```bash
python -I -S -B scripts/demo_first_run.py --json
```

The JSON includes each observed check, process exit codes, the **complete** original failed log, the compacted log, the symbol location, and SHA-256 hashes of the original, broken, and restored file. Successful hashes satisfy `original == restored` and `original != broken`. Timing and estimated token savings are deliberately omitted.

The captured traceback includes an absolute temporary path. That directory has been removed when the report is returned. Redirect output to a file yourself if you want to keep the evidence.

## What this does not establish

- The edit is scripted. ROMS neither discovers a fix nor asks a model to produce one.
- The log contains generated progress messages and a real Python exception. Its compression ratio is not a claim about other projects or logs.
- The symbol indexer uses pattern matching here. This demonstration does not establish complete AST analysis, a call graph, or stale-index protection.
- Recovery is limited to one known file in an isolated workspace. It does not establish transactional multi-file recovery, integrity of untrusted snapshot stores, or preservation of concurrent user edits. Do not treat this demo as authorization to rewind a real workspace.
- No MCP client, GPU, Mojo kernel, embedding model, RWKV runtime, semantic retrieval, or future-machine performance is exercised.

The next step for real use is the [existing MCP setup](../README.md#-10-second-mcp-setup-claude-code-cursor-windsurf). Choose individual tools and review their operating boundaries before giving an agent access to a project.

## Regression checks

These checks also use only the Python standard library:

```bash
python -m unittest discover -s tests -p test_first_run_demo.py -v
```

They run the command outside the checkout with third-party packages disabled, preserve a caller-owned file and configured ROMS data location, reject a compacted log that loses its error, reject a false successful restore, require the restored program to pass, verify cleanup on failure, and require a nonzero exit code when evidence is missing.

Checked on 2026-10-06: the five new demo tests and five existing `test_prefrontal_integration.py` tests passed on Windows with Python 3.14 and Linux with Python 3.12 (**10 passed on each platform**). The Windows pytest run used a fresh workspace-local temporary directory because the shared pytest temporary directory was not accessible. The no-install command and standard-library unittest command also passed on Windows.
