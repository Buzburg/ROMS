#!/usr/bin/env python3
"""
Automated GitHub Repo Creator, Topic SEO Optimizer & Directory PR Submitter (`launch/submit_directory_prs.py`)
==============================================================================================================
Uses the GitHub CLI (`gh`) to:
1. Optionally create & push the public GitHub repository (`--create-repo`).
2. Tag your `mojo-cortex` GitHub repository with the top 15 high-traffic discovery topics.
3. Automatically fork, clone, insert `mojo-cortex` into the appropriate README section
   (Memory / Developer Tools, before License/Contributing), and open Pull Requests on:
   - `punkpeye/awesome-mcp-servers`
   - `wong2/awesome-mcp-servers`
   - `appcypher/awesome-mcp-servers`
"""

import os
import re
import sys
import shutil
import tempfile
import subprocess
import argparse

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def insert_entry_into_readme(content: str, entry: str) -> str:
    """Inserts the markdown entry into the Memory / Developer Tools section or before License/Contributing."""
    lines = content.splitlines()
    target_idx = -1

    # 1. Try to find a Memory, Knowledge, Coding, or Developer Tools section and append to its list
    section_pattern = re.compile(r"^#{2,4}\s+.*(Memory|Knowledge|Developer Tools|Coding|Code|Tools)", re.IGNORECASE)
    in_target_section = False
    for i, line in enumerate(lines):
        if section_pattern.match(line):
            in_target_section = True
            continue
        if in_target_section:
            if line.startswith("#"):
                target_idx = i
                break
            if line.strip().startswith("- ") or line.strip().startswith("* "):
                target_idx = i + 1

    # 2. Fallback: insert right before ## License or ## Contributing
    if target_idx == -1:
        footer_pattern = re.compile(r"^#{1,3}\s+(License|Contributing|Star History|Acknowledgements)", re.IGNORECASE)
        for i, line in enumerate(lines):
            if footer_pattern.match(line):
                target_idx = max(0, i - 1)
                break

    if target_idx == -1:
        return content.rstrip() + "\n" + entry + "\n"

    lines.insert(target_idx, entry)
    return "\n".join(lines) + "\n"


def create_and_push_repo(repo_slug: str, dry_run: bool = False):
    desc = "Universal Prefrontal Cortex, Associative Memory (Titans + DeltaNet-2), 98.8% SnapKV Log Sieve & Safety MCP Harness in Mojo 1.1.0 + Python"
    cmd = [
        "gh", "repo", "create", repo_slug,
        "--public",
        "--source", ROOT_DIR,
        "--remote", "origin",
        "--description", desc,
        "--push"
    ]
    if dry_run:
        print(f"[DRY-RUN] Would create and push public GitHub repo:\n  {' '.join(cmd)}")
        return
    code, out, err = run_cmd(cmd, cwd=ROOT_DIR)
    if code == 0:
        print(f"[+] Created and pushed public repo: {out}")
    else:
        print(f"[*] Repo create status (may already exist): {err or out}")


def apply_github_seo_topics(repo_slug: str, dry_run: bool = False):
    cmd = ["gh", "repo", "edit", repo_slug]
    for t in SEO_TOPICS:
        cmd.extend(["--add-topic", t])
    if dry_run:
        print(f"[DRY-RUN] Would tag {repo_slug} with {len(SEO_TOPICS)} SEO topics:\n  {' '.join(cmd)}")
        return
    code, out, err = run_cmd(cmd, cwd=ROOT_DIR)
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
        print(f"[DRY-RUN] Would fork `{target_repo}`, insert entry into the Memory/Tools section of README.md, and run `gh pr create`:")
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
                updated = insert_entry_into_readme(content, entry)
                with open(readme_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(updated)
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
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Automated GitHub Repo Creator, SEO & Awesome-MCP PR Submitter")
    parser.add_argument("--repo-slug", default="Buzburg/mojo-cortex")
    parser.add_argument("--repo-url", default="https://github.com/Buzburg/mojo-cortex")
    parser.add_argument("--create-repo", action="store_true", help="Create and push public GitHub repo via gh CLI")
    parser.add_argument("--execute", action="store_true", help="Execute live gh CLI commands (default is dry-run)")
    args = parser.parse_args()

    dry = not args.execute
    if args.create_repo:
        create_and_push_repo(args.repo_slug, dry_run=dry)
    apply_github_seo_topics(args.repo_slug, dry_run=dry)
    for target in AWESOME_REPOS:
        submit_awesome_pr(target, args.repo_url, dry_run=dry)


if __name__ == "__main__":
    main()
