# Reproducible model inputs — October 5, 2026

`config/build-inputs.json` records exact filenames, sizes and SHA-256 identities for the two supplied GGUF models, the default 2.9B selection, the native runtime repository/revision and the unchanged reviewed `pixi.lock` identity. These initially identified only user-supplied bytes. A subsequent [compatibility and provenance check](model-compatibility-verification.md) matched both against immutable publisher LFS records and added the actual pinned download URLs. The 7.2B model remains deferred for deployment/training.

## Use

From the installed Python environment, run `python scripts/download_rwkv7.py --model 2.9b` to verify the supplied file in the parent workspace. `--target-dir` selects another containing folder. Verification checks a regular non-symlink `.gguf` file, its exact size, the little-endian GGUF v3 header, its full SHA-256, and file identity before/after hashing. This does not load the model, rename formats, quantize a checkpoint or certify inference compatibility.

`--dry-run` emits `planned_not_verified`; it does not hash files, create folders or access the network. To acquire missing bytes, explicitly supply `--url` with an operator-reviewed HTTPS source. The download must still match the selected manifest identity. The tool does not discover or certify that URL's publisher. An existing matching cache is reverified without network access; an existing mismatch is preserved and rejected rather than replaced.

Transfers reject non-200 responses, mismatching declared lengths, compressed transport and excess/truncated bytes. They use a 30-second socket timeout and 30-minute loop deadline, with a unique same-directory temporary file. HTTPS redirects cannot downgrade to HTTP or add URL credentials. The expected hash and GGUF header must pass before a flushed, synchronized file is published through a no-replace hard link. Failures/cancellation remove only the owned temporary file; a concurrently created destination is preserved. Filesystems without hard-link support fail instead of falling back to overwrite.

The GGUF header layout follows the [official GGML format specification](https://github.com/ggml-org/ggml/blob/master/docs/gguf.md). The verifier identifies the header and known full byte identity; it does not claim to independently validate every tensor record. Actual runtime loading remains a separate compatibility gate.

## Runtime and environment

`scripts/build_llama.py` reads the pinned runtime source revision from the same manifest. It refuses modified source even when HEAD already matches the revision, refuses an unexpected origin, and verifies HEAD and source cleanliness again before configuring/building. It builds the existing CPU configuration without installing a service. The obsolete unpinned `--build-librwkv` path now fails with a pointer to this builder; downloading a `.pth` checkpoint under a quantized `.bin` label is no longer supported.

The current checked-in environment lockfile has SHA-256 `e45f9ec7a71ebf696280f78db4f8490d949358866fbd67c00ca70094ee667e86`. The October 19, 2026 MCP policy upgrade raises FastMCP to the tested 4.1 series and refreshes this fingerprint. The resolved update changes FastMCP and fastmcp-slim from 4.0.10 to 4.1.1; model identities and other locked packages remain unchanged. Use the checked-in lockfile for environment reproduction; changed lock contents require a deliberate review and manifest update. No model weights or inference configuration change with this update.

At that increment, the installed server reported `0.5.0-dev`, build 1, commit `46847e6`, built with GNU 13.3.0 for Linux x86_64. Its artifact identities were measured directly; the later [cancellation repair](gateway-cancellation-verification.md) records the currently installed derived build and preserves this runtime for rollback:

| Artifact under `/opt/goose-runtime/bin` | SHA-256 |
|---|---|
| `llama-server` | `dc77cdc9313c75883f4c175b911dc99763dad82b111113b1ea54606a9e77cf61` |
| `libllama-server-impl.so` | `b069acf9eb3d7e4b188815da70a332c0936d9f8a6b98de0e9e68ede8f32d6226` |
| `libllama.so` | `b6f5153d594eb52b821717d30332783056078468ad13584aeed86b59784f6239` |

These hashes describe the installed build, not a claim of bit-for-bit reproducible compiler output on other hardware. The direct native C adapter is still unimplemented. Model files, training weights, ISO files, databases and private configuration are excluded from the source baseline; the reviewed lockfile remains tracked.

## Evidence

The focused acquisition/input suite passed **23 tests** without contacting an external server. It covers success/cache revalidation, wrong size/hash/header, interrupted reads, 404 during open, cancellation, retained invalid cache, concurrent destination preservation, unsafe URLs and redirect downgrade, symlink refusal, dry-run side effects, lockfile identity and dirty/unexpected native-source refusal. The fixed offline regression inventory now includes this suite.

The actual supplied 2.9B file passed the new CLI: 1,919,047,616 bytes and SHA-256 `72f0fbb674ca21acf035b66023083055f6cede4942deb1f1b8475390752cfdf3`. Publisher provenance remained explicitly unverified. No remote model was downloaded and no training was started.

The supplied 7.2B file also passed the new CLI: 7,930,820,544 bytes and SHA-256 `cc93dce01fb8750627e4ba2a853de7803655b2fa65b74206587a5d9620bba14f`. This was a read-only file verification; the installed service continues using 2.9B.

The expanded offline profile passed both required groups: **177 Python regression tests and 22 actual compiled native-broker tests**. Git's tracked-file inventory contained the reviewed lockfile and no model weights, ISO, runtime database or `.env`; exclusion checks confirmed the additional model/ISO patterns. Unrelated pending source files were left untouched.
