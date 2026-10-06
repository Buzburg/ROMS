#!/usr/bin/env python3
"""
Automated GitHub Directory PR Submitter & Topic SEO Optimizer (`launch/submit_directory_prs.py`)
===============================================================================================
Uses the GitHub CLI (`gh`) to:
1. Automatically tag your `mojo-cortex` GitHub repository with the top 15 high-traffic
   discovery topics (`mcp`, `model-context-protocol`, `claude-code`, `cursor`, `mojo`, etc.).
2. Automatically fork, clone, add `mojo-cortex`, and open Pull Requests on the top
   Awesome-MCP repositories (`punkpeye/awesome-mcp-servers`, `wong2/awesome-mcp-servers`,
   `appcypher/awesome-mcp-servers`).
"""

import os
import sys
import shutil
import tempfile
import subprocess
import argparse

AWESOME_REPOS = [
    "punkpeye/awesome-mcp-servers",
    "wong2/awesome-mcp-servers",
    "appcypher/awesome-mcp-servers",
]

SEO_TOPICS = [
    "mcp",
    "model-context-protocol",
    "mojo",
    "ai-agents",
    "claude-code",
    "cursor",
    "localllama",
    "bitnet",
    "titans",
    "deltanet",
    "snapkv",
    "llm-memory",
    "context-compression",
    "agent-harness",
    "rwkv",
]


def run_cmd(cmd: list, cwd: str = None) -> tuple:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def apply_github_seo_topics(repo_slug: str, dry_run: bool = False):
    cmd = ["gh", "repo", "edit", repo_slug]
    for t in SEO_TOPICS:
        cmd.extend(["--add-topic", t])
    if dry_run:
        print(f"[DRY-RUN] Would tag {repo_slug} with {len(SEO_TOPICS)} SEO topics:\n  {' '.join(cmd)}")
        return
    code, out, err = run_cmd(cmd)
    if code == 0:
        print(f"[+] Tagged {repo_slug} with {len(SEO_TOPICS)} high-discovery GitHub topics.")
    else:
        print(f"[-] Could not tag {repo_slug}: {err}")


def submit_awesome_pr(target_repo: str, my_repo_url: str, dry_run: bool = False):
    entry = (
        f"- [mojo-cortex]({my_repo_url}) - Universal Prefrontal Cortex, Associative Memory "
        f"(Titans + Gated DeltaNet-2), 98.8% SnapKV Log Sieve, 25.61x Mojo 1.1.0 Knapsack "
        f"Context Packer, CoW Time Machine & Safety Harness for AI Coding Agents."
    )
    pr_title = "Add mojo-cortex (Associative Memory, 98.8% Log Sieve & Safety Harness MCP)"
    pr_body = (
        f"## Summary\n"
        f"Adds **[mojo-cortex]({my_repo_url})**, a zero-dependency Model Context Protocol (MCP) server "
        f"powered by native Mojo 1.1.0 kernels and Python:\n\n"
        f"- **Hybrid Neural Memory:** Google's *Titans* (`2501.00663`) + *Gated DeltaNet-2* (`2605.22791`) "
        f"with `1.0000` cosine key overwrite and surgical key deletion.\n"
        f"- **0/1 Knapsack Context Packer (`25.61x` Mojo 1.1.0 speedup):** Reserves failed-attempt warnings first "
        f"so agents never repeat failed repairs.\n"
        f"- **SnapKV Context Sieve:** Compacts verbose build/test logs by `98.8%` while preserving 100% of stack traces.\n"
        f"- **Git-Safe CoW Time Machine & Pre-Execution Shield:** Atomic `<5 ms` workspace rollback without altering `.git`.\n"
    )

    if dry_run:
        print(f"[DRY-RUN] Would fork `{target_repo}`, insert entry into README.md, and run `gh pr create`:")
        print(f"  Entry: {entry}")
        return

    tmp = tempfile.mkdtemp(prefix="awesome_pr_")
    try:
        print(f"[*] Forking and cloning {target_repo}...")
        code, _, err = run_cmd(["gh", "repo", "fork", target_repo, "--clone=true"], cwd=tmp)
        repo_name = target_repo.split("/")[1]
        clone_dir = os.path.join(tmp, repo_name)
        if not os.path.exists(clone_dir):
            print(f"[-] Clone failed for {target_repo}: {err}")
            return

        run_cmd(["git", "checkout", "-b", "add-mojo-cortex"], cwd=clone_dir)
        readme_path = os.path.join(clone_dir, "README.md")
        if os.path.exists(readme_path):
            with open(readme_path, "r", encoding="utf-8") as f:
                content = f.read()
            if my_repo_url not in content:
                content = content.rstrip() + "\n" + entry + "\n"
                with open(readme_path, "w", encoding="utf-8") as f:
                    f.write(content)
                run_cmd(["git", "add", "README.md"], cwd=clone_dir)
                run_cmd(["git", "commit", "-m", pr_title], cwd=clone_dir)
                run_cmd(["git", "push", "-u", "origin", "add-mojo-cortex"], cwd=clone_dir)
                code, out, err = run_cmd(
                    ["gh", "pr", "create", "--repo", target_repo, "--title", pr_title, "--body", pr_body],
                    cwd=clone_dir
                )
                print(f"[+] Opened PR on {target_repo}: {out or err}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Automated GitHub SEO & Awesome-MCP PR Submitter")
    parser.add_argument("--repo-slug", default="Buzburg/mojo-cortex")
    parser.add_argument("--repo-url", default="https://github.com/Buzburg/mojo-cortex")
    parser.add_argument("--execute", action="store_true", help="Execute live gh CLI commands (default is dry-run)")
    args = parser.parse_args()

    dry = not args.execute
    apply_github_seo_topics(args.repo_slug, dry_run=dry)
    for target in AWESOME_REPOS:
        submit_awesome_pr(target, args.repo_url, dry_run=dry)


if __name__ == "__main__":
    main()
