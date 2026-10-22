# Local enhancement reference review

Triaged 132 ZIP archives under the supplied ROMS Data collection by archive directory, root README and available license files. The Enhancements, Skills and Any collections were prioritized. This is reference triage, not a full code or security audit. Archives and scripts were not executed. No third-party source code was copied; this release contains original ROMS implementations of selected design ideas.

## Selected ideas

- `autoskills-main.zip`: content hashes and explicit provenance.
- `OpenSpace-main.zip`: retrieval, source revisions and outcome feedback.
- `book-to-skill-master.zip`: source-grounded portable procedural drafts.
- `book2skills-main.zip`: procedures with applicability and validation context.
- `one-skill-to-rule-them-all-main.zip`: revision-specific observations; changes remain reviewable.
- `UpSkill-main.zip`: extend the existing trajectory-draft path with knowledge-derived drafts.
- `AnyTool-main.zip`: retrieve relevant capabilities instead of loading the entire catalog.
- `RAG-Anything-main.zip`: retain source references through ingestion and retrieval.
- `MGP-main.zip`: identity and lifecycle boundaries.
- `AutoMemory-main.zip`: deduplication and invalidation when evidence changes.
- `SkillOpt-main.zip`: measure changes rather than assert automatic quality gains.
- `CLI-Anything-main.zip`: a typed, testable CLI surface.
- `docker-agent-main.zip`: local integration surface; no additional orchestration runtime.

The implementation deliberately reuses ROMS SQLite ingestion, existing source checksums, native text parsing, MCP policy and local HTTP stack. Remote registries, new agent runtimes, self-modifying code, speculative optimization, and automatic execution were not adopted. Additional archives were triaged as reference material for future work; they are not claimed as integrated.

## Archive inventory

| Archive | Members | Root license file | Disposition |
| --- | ---: | --- | --- |
| Additional/dembrandt-main.zip | 236 | LICENSE | Reference triage; not integrated |
| Additional/dembrandt-skills-main.zip | 110 | LICENSE | Reference triage; not integrated |
| Additional/ghidra-master/GPL/DMG/data/lib/hfsexplorer-0_21-src.zip | 559 | LICENSE.txt | Reference triage; not integrated |
| Additional/ghidra-master.zip | 25172 | LICENSE | Reference triage; not integrated |
| Additional/leanrea-main.zip | 16 | LICENSE | Reference triage; not integrated |
| Additional/open-code-review-main.zip | 1312 | LICENSE | Reference triage; not integrated |
| Additional/rea-main.zip | 4077 | LICENSE | Reference triage; not integrated |
| Additional/reverse-skill-main.zip | 881 | LICENSE | Reference triage; not integrated |
| Additional/screenshot-to-code-main.zip | 376 | LICENSE | Reference triage; not integrated |
| Additional/zvec-main.zip | 1889 | LICENSE | Reference triage; not integrated |
| Agents/Auto-Deep-Research-main.zip | 88 | Not found in root scan; no copying | Reference triage; not integrated |
| Agents/AutoAgent-main.zip | 356 | LICENSE | Reference triage; not integrated |
| Agents/AutoMemory-main.zip | 28578 | Not found in root scan; no copying | Duplicate/reference triage |
| Agents/CatchMe-main.zip | 129 | LICENSE | Reference triage; not integrated |
| Agents/ClawTeam-main.zip | 238 | LICENSE | Reference triage; not integrated |
| Agents/DeepInnovator-main.zip | 631 | LICENSE | Reference triage; not integrated |
| Agents/HELIX-main.zip | 1110 | LICENSE | Reference triage; not integrated |
| Agents/MGP-main.zip | 362 | LICENSE | Duplicate/reference triage |
| Agents/OpenSpace-main.zip | 1724 | LICENSE | Duplicate/reference triage |
| Agents/RSIAgent-main.zip | 208 | LICENSE | Reference triage; not integrated |
| Agents/Sage-main.zip | 3639 | LICENSE | Reference triage; not integrated |
| Agents/Skill-RSI-main.zip | 282 | Not found in root scan; no copying | Reference triage; not integrated |
| Agents/The-Living-Agent-main.zip | 4622 | LICENSE | Reference triage; not integrated |
| Agents/agency-agents-main.zip | 434 | LICENSE | Reference triage; not integrated |
| Agents/agent-apprenticeship-main.zip | 80 | LICENSE | Reference triage; not integrated |
| Agents/agent-console-main.zip | 205 | LICENSE-APACHE, LICENSE-MIT | Reference triage; not integrated |
| Agents/agent-of-empires-main.zip | 2060 | LICENSE | Reference triage; not integrated |
| Agents/agent-orchestr-main.zip | 35 | LICENSE | Reference triage; not integrated |
| Agents/agent-orchestrator-main.zip | 5327 | LICENSE | Reference triage; not integrated |
| Agents/agent-squad-main.zip | 829 | LICENSE | Reference triage; not integrated |
| Agents/autoagent-main.zip | 11 | Not found in root scan; no copying | Reference triage; not integrated |
| Agents/autoevolve-main.zip | 1023 | LICENSE | Reference triage; not integrated |
| Agents/autoharness-main.zip | 113 | LICENSE | Reference triage; not integrated |
| Agents/autoresearch-master.zip | 11 | Not found in root scan; no copying | Reference triage; not integrated |
| Agents/cli-agent-orchestrator-main.zip | 2131 | LICENSE | Reference triage; not integrated |
| Agents/docker-agent-main.zip | 3785 | LICENSE | Duplicate/reference triage |
| Agents/harness-evolver-main.zip | 120 | LICENSE | Reference triage; not integrated |
| Agents/localdoc-search-main.zip | 31 | LICENSE | Reference triage; not integrated |
| Agents/mojo-agent-rewind-main.zip | 9 | LICENSE | Reference triage; not integrated |
| Agents/mojo-compact-kv-master.zip | 9 | LICENSE | Reference triage; not integrated |
| Agents/mojo-drift-master.zip | 9 | LICENSE | Reference triage; not integrated |
| Agents/mojo-fastgate-master.zip | 9 | LICENSE | Reference triage; not integrated |
| Agents/mojo-local-horizon-master.zip | 9 | LICENSE | Reference triage; not integrated |
| Agents/mojo-memory-main.zip | 20 | LICENSE | Reference triage; not integrated |
| Agents/mojo-micro-toolcall-master.zip | 9 | LICENSE | Reference triage; not integrated |
| Agents/mojo-sieve-master.zip | 9 | LICENSE | Reference triage; not integrated |
| Agents/mojo-skillcheck-master.zip | 9 | LICENSE | Reference triage; not integrated |
| Agents/mojo-symdex-master.zip | 9 | LICENSE | Reference triage; not integrated |
| Agents/moli-main.zip | 8623 | LICENSE-APACHE, LICENSE-MIT | Reference triage; not integrated |
| Agents/prime-agent-main.zip | 1860 | LICENSE | Reference triage; not integrated |
| Agents/repomon-main.zip | 823 | LICENSE | Reference triage; not integrated |
| Agents/serena-main.zip | 1592 | LICENSE | Reference triage; not integrated |
| Agents/skillcheck-master.zip | 18 | LICENSE | Reference triage; not integrated |
| Agents/statefresh-main.zip | 20 | LICENSE | Reference triage; not integrated |
| Agents/triad-engine-main.zip | 107 | LICENSE | Reference triage; not integrated |
| Agents/workflowproof-main.zip | 22 | LICENSE | Reference triage; not integrated |
| Any/AnyTool-main.zip | 167 | LICENSE | Duplicate/reference triage |
| Any/CLI-Anything-main.zip | 2583 | LICENSE | Duplicate/reference triage |
| Any/RAG-Anything-main.zip | 146 | LICENSE | Duplicate/reference triage |
| Enhancements/AnyTool-main.zip | 167 | LICENSE | Selected design reference |
| Enhancements/AutoMemory-main.zip | 28578 | Not found in root scan; no copying | Selected design reference |
| Enhancements/CLI-Anything-main.zip | 2583 | LICENSE | Selected design reference |
| Enhancements/MGP-main.zip | 362 | LICENSE | Selected design reference |
| Enhancements/OpenSpace-main.zip | 1724 | LICENSE | Selected design reference |
| Enhancements/RAG-Anything-main.zip | 146 | LICENSE | Selected design reference |
| Enhancements/SkillOpt-main.zip | 581 | LICENSE | Selected design reference |
| Enhancements/UpSkill-main.zip | 1396 | LICENSE | Selected design reference |
| Enhancements/autoskills-main.zip | 5400 | LICENSE | Selected design reference |
| Enhancements/book-to-skill-master.zip | 147 | LICENSE.md | Selected design reference |
| Enhancements/book2skills-main.zip | 498 | LICENSE | Selected design reference |
| Enhancements/docker-agent-main.zip | 3941 | LICENSE | Selected design reference |
| Enhancements/one-skill-to-rule-them-all-main.zip | 36 | LICENSE.txt | Selected design reference |
| Extra/AI-Researcher-main.zip | 1614 | Not found in root scan; no copying | Reference triage; not integrated |
| Extra/AutoMemory-main/use_cases/opencode-dev-17701628b/packages/console/app/public/opencode-brand-assets.zip | 30 | Not found in root scan; no copying | Reference triage; not integrated |
| Extra/AutoMemory-main/use_cases/opencode-dev-17701628b/packages/console/app/src/asset/brand/opencode-brand-assets.zip | 30 | Not found in root scan; no copying | Reference triage; not integrated |
| Extra/AutoMemory-main.zip | 28578 | Not found in root scan; no copying | Duplicate/reference triage |
| Extra/DeepInnovator-main.zip | 631 | LICENSE | Reference triage; not integrated |
| Extra/DeepResearch-Eval-main.zip | 22 | Not found in root scan; no copying | Reference triage; not integrated |
| Extra/FastCode-main.zip | 149 | Not found in root scan; no copying | Reference triage; not integrated |
| Extra/FutureShow-main.zip | 95 | LICENSE | Reference triage; not integrated |
| Extra/LightReasoner-main.zip | 39 | LICENSE | Reference triage; not integrated |
| Extra/OpenSpace-main.zip | 1724 | LICENSE | Duplicate/reference triage |
| Extra/ccpm-main.zip | 33 | LICENSE | Reference triage; not integrated |
| Extra/coding-tools-mcp-main.zip | 366 | LICENSE | Reference triage; not integrated |
| Extra/loop-engineering-main.zip | 951 | LICENSE | Reference triage; not integrated |
| Skills/UpSkill-main.zip | 1396 | LICENSE | Duplicate/reference triage |
| Skills/agent-skills-main.zip | 314 | LICENSE | Reference triage; not integrated |
| Skills/agentic-awesome-skills-main.zip | 39928 | LICENSE, LICENSE-CONTENT | Reference triage; not integrated |
| Skills/ai-skills-master.zip | 354 | LICENSE | Reference triage; not integrated |
| Skills/skills-main.zip | 289 | LICENSE | Reference triage; not integrated |
| harness/Coder/GeneticEngine-main.zip | 391 | Not found in root scan; no copying | Reference triage; not integrated |
| harness/Coder/TinyverseGP-main.zip | 319 | LICENSE | Reference triage; not integrated |
| harness/Coder/create-t3-app-main.zip | 659 | LICENSE | Reference triage; not integrated |
| harness/Coder/create-t3-turbo-main.zip | 198 | LICENSE | Reference triage; not integrated |
| harness/Coder/jev-review-main.zip | 45 | LICENSE | Reference triage; not integrated |
| harness/Coder/proa-main.zip | 2947 | LICENSE | Reference triage; not integrated |
| harness/Coder/rosette-master.zip | 536 | LICENSE | Reference triage; not integrated |
| harness/Coder/z3-master.zip | 2959 | LICENSE.txt | Reference triage; not integrated |
| harness/Debugger Agent/AgentDebug-main.zip | 631 | LICENSE | Reference triage; not integrated |
| harness/Debugger Agent/FixBug-core-main.zip | 21 | LICENSE | Reference triage; not integrated |
| harness/Debugger Agent/LookMeNot-main.zip | 126 | LICENSE | Reference triage; not integrated |
| harness/Debugger Agent/agent-debugger-main.zip | 52 | LICENSE | Reference triage; not integrated |
| harness/Debugger Agent/ane-main.zip | 187 | LICENSE | Reference triage; not integrated |
| harness/Debugger Agent/browsertrace-main.zip | 124 | LICENSE | Reference triage; not integrated |
| harness/Debugger Agent/debug-agent-main (1).zip | 181 | LICENSE | Reference triage; not integrated |
| harness/Debugger Agent/debug-agent-main.zip | 181 | LICENSE | Reference triage; not integrated |
| harness/Debugger Agent/debugger-agent-main.zip | 71 | LICENSE.txt | Reference triage; not integrated |
| harness/Debugger Agent/jdb-agentic-debugger-main.zip | 72 | LICENSE | Reference triage; not integrated |
| harness/Debugger Agent/multiagent-debugger-main.zip | 40 | LICENSE | Reference triage; not integrated |
| harness/HELIX-main.zip | 1110 | LICENSE | Reference triage; not integrated |
| harness/OpenHarness-main.zip | 581 | LICENSE | Reference triage; not integrated |
| harness/RSIAgent-main.zip | 208 | LICENSE | Reference triage; not integrated |
| harness/Raven-main.zip | 5067 | LICENSE | Reference triage; not integrated |
| harness/Sage-main.zip | 3639 | LICENSE | Reference triage; not integrated |
| harness/Skill-RSI-main.zip | 282 | Not found in root scan; no copying | Reference triage; not integrated |
| harness/The-Living-Agent-main.zip | 4622 | LICENSE | Reference triage; not integrated |
| harness/autoevolve-main.zip | 1023 | LICENSE | Reference triage; not integrated |
| harness/autoharness-main.zip | 113 | LICENSE | Reference triage; not integrated |
| harness/docker-agent-main.zip | 3785 | LICENSE | Duplicate/reference triage |
| harness/harness-evolver-main.zip | 120 | LICENSE | Reference triage; not integrated |
| harness/harness2-main.zip | 153 | LICENSE | Reference triage; not integrated |
| harness/herdr-hud-main.zip | 60 | LICENSE | Reference triage; not integrated |
| harness/hindsight-main/hindsight-system-evals/fixtures/beir-scifact-bank.zip | 511 | Not found in root scan; no copying | Reference triage; not integrated |
| harness/hindsight-main/hindsight-system-evals/fixtures/refresh-cost-bank.zip | 21 | Not found in root scan; no copying | Reference triage; not integrated |
| harness/hindsight-main.zip | 5748 | LICENSE | Reference triage; not integrated |
| harness/octop/Octop-main.zip | 4348 | LICENSE | Reference triage; not integrated |
| harness/octop/octop-browser-main.zip | 126 | LICENSE | Reference triage; not integrated |
| harness/octop/octop-gateway-main.zip | 134 | LICENSE | Reference triage; not integrated |
| harness/octop/octop-harness-main.zip | 738 | LICENSE | Reference triage; not integrated |
| harness/octop/octop-memory-main.zip | 325 | LICENSE | Reference triage; not integrated |
| harness/polyharness-master.zip | 24 | LICENSE | Reference triage; not integrated |
| harness/prime-agent-main.zip | 1860 | LICENSE | Reference triage; not integrated |
