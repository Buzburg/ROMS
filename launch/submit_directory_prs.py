#!/usr/bin/env python3
"""
Automated GitHub Repo Creator, Topic SEO Optimizer & Directory PR Submitter (`launch/submit_directory_prs.py`)
==============================================================================================================
Uses the GitHub CLI (`gh`) to:
1. Optionally create & push the public GitHub repository (`--create-repo`).
2. Tag your `cortex` GitHub repository with the top 15 high-traffic discovery topics.
3. Create an official GitHub Release (`v1.1.0`) with verified benchmark notes.
4. Automatically fork, clone, insert `cortex` into the appropriate README section
   (Memory / Developer Tools, before License/Contributing), and open Pull Requests on:
   - `punkpeye/awesome-mcp-servers`
   - `wong2/awesome-mcp-servers`
   - `appcypher/awesome-mcp-servers`
"""

import os
import re
import sys
import shlex
import shutil
import tempfile
import subprocess
import argparse

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALLBACK_GH = r"D:\Buzburg Files\Github\Github Gemini\output\buzburg-release\github-cli\bin\gh.exe"
FALLBACK_AUTH = r"D:\Buzburg Files\Github\Github Gemini\output\buzburg-release\github-auth"

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


def resolve_gh_env() -> tuple:
    gh_bin = shutil.which("gh") or (FALLBACK_GH if os.path.exists(FALLBACK_GH) else "gh")
    env = dict(os.environ, GH_PROMPT_DISABLED="1")
    if "GH_CONFIG_DIR" not in env and os.path.exists(FALLBACK_AUTH):
        env["GH_CONFIG_DIR"] = FALLBACK_AUTH
    return gh_bin, env


def run_cmd(cmd: list, cwd: str = None) -> tuple:
    gh_bin, env = resolve_gh_env()
    resolved_cmd = [gh_bin if (i == 0 and c == "gh") else str(c) for i, c in enumerate(cmd)]
    proc = subprocess.run(resolved_cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def git_with_gh_auth(cwd: str, *git_args) -> tuple:
    gh_bin, _ = resolve_gh_env()
    gh_posix = gh_bin.replace("\\", "/")
    helper = f"!{shlex.quote(gh_posix)} auth git-credential"
    cmd = [
        "git",
        "-c", "credential.helper=",
        "-c", f"credential.helper={helper}",
        "-c", "credential.interactive=never",
        *git_args
    ]
    return run_cmd(cmd, cwd=cwd)


def insert_entry_into_readme(content: str, entry: str) -> str:
    """Inserts the markdown entry into the Memory / Developer Tools section or before License/Contributing."""
    lines = content.splitlines()
    target_idx = -1

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
    if dry_run:
        print(f"[DRY-RUN] Would create and push public GitHub repo: {repo_slug}")
        return

    code, out, err = run_cmd(["gh", "api", f"repos/{repo_slug}"], cwd=ROOT_DIR)
    if code != 0:
        c2, o2, e2 = run_cmd(["gh", "repo", "create", repo_slug, "--public", "--description", desc], cwd=ROOT_DIR)
        print(f"[+] Created public repo {repo_slug}: {o2 or e2}")
    else:
        run_cmd(["gh", "repo", "edit", repo_slug, "--visibility", "public", "--accept-visibility-change-consequences", "--description", desc], cwd=ROOT_DIR)
        print(f"[+] Verified public repo {repo_slug}")

    remote_url = f"https://github.com/{repo_slug}.git"
    run_cmd(["git", "remote", "remove", "origin"], cwd=ROOT_DIR)
    run_cmd(["git", "remote", "add", "origin", remote_url], cwd=ROOT_DIR)
    c_push, o_push, e_push = git_with_gh_auth(ROOT_DIR, "push", "-u", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/master", "--force")
    if c_push == 0:
        print(f"[+] Pushed cortex to https://github.com/{repo_slug}")
    else:
        print(f"[-] Push error: {e_push or o_push}")


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


def create_github_release(repo_slug: str, dry_run: bool = False):
    if dry_run:
        print(f"[DRY-RUN] Would create v1.1.0 GitHub Release on {repo_slug}")
        return
    notes_path = os.path.join(ROOT_DIR, "verification.md")
    code, out, err = run_cmd([
        "gh", "release", "create", "v1.1.0",
        "--repo", repo_slug,
        "--title", "cortex v1.1.0 — Native Mojo 1.1.0 Kernels (25.61x Speedup), Titans+DeltaNet-2 Memory & 10 MCP Tools",
        "--notes-file", notes_path
    ], cwd=ROOT_DIR)
    if code == 0:
        print(f"[+] Published official GitHub Release v1.1.0: {out}")
    else:
        print(f"[*] Release status: {err or out}")


def submit_awesome_pr(target_repo: str, my_repo_url: str, dry_run: bool = False):
    entry = (
        f"- [cortex]({my_repo_url}) - Universal Prefrontal Cortex, Associative Memory "
        f"(Titans + Gated DeltaNet-2), 98.8% SnapKV Log Sieve, 25.61x Mojo 1.1.0 Knapsack "
        f"Context Packer, CoW Time Machine & Safety Harness for AI Coding Agents."
    )
    pr_title = "Add cortex (Associative Memory, 98.8% Log Sieve & Safety Harness MCP)"
    pr_body = (
        f"## Summary\n"
        f"Adds **[cortex]({my_repo_url})**, a zero-dependency Model Context Protocol (MCP) server "
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
        target_owner, repo_name = target_repo.split("/")
        fork_name = repo_name if target_owner == "punkpeye" else f"{target_owner}-{repo_name}"
        print(f"[*] Forking {target_repo} as {fork_name}...")
        run_cmd(["gh", "repo", "fork", target_repo, "--fork-name", fork_name, "--clone=false"], cwd=tmp)
        _, owner, _ = run_cmd(["gh", "api", "user", "--jq", ".login"], cwd=tmp)
        fork_url = f"https://github.com/{owner}/{fork_name}.git"
        upstream_url = f"https://github.com/{target_repo}.git"

        clone_dir = os.path.join(tmp, fork_name)
        c_clone, _, e_clone = git_with_gh_auth(tmp, "clone", "--depth", "1", upstream_url, clone_dir)
        if c_clone != 0 or not os.path.exists(clone_dir):
            print(f"[-] Clone failed for {target_repo}: {e_clone}")
            return

        _, default_branch, _ = run_cmd(["gh", "api", f"repos/{target_repo}", "--jq", ".default_branch"], cwd=clone_dir)
        default_branch = default_branch or "main"

        run_cmd(["git", "checkout", "-b", "add-cortex"], cwd=clone_dir)
        readme_path = os.path.join(clone_dir, "README.md")
        if os.path.exists(readme_path):
            with open(readme_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if my_repo_url not in content:
                updated = insert_entry_into_readme(content, entry)
                with open(readme_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(updated)
                run_cmd(["git", "add", "README.md"], cwd=clone_dir)
                c_c, o_c, e_c = run_cmd(
                    ["git", "-c", "user.name=Buzburg AI", "-c", "user.email=dev@buzburg.ai", "commit", "-m", pr_title],
                    cwd=clone_dir
                )
                if c_c != 0:
                    print(f"[-] Commit failed in {target_repo}: {e_c or o_c}")
                    return
                c_p, o_p, e_p = git_with_gh_auth(clone_dir, "push", "-u", fork_url, "HEAD:refs/heads/add-cortex", "--force")
                if c_p != 0:
                    print(f"[-] Push to fork {fork_url} failed: {e_p or o_p}")
                    return
                code, out, err = run_cmd(
                    [
                        "gh", "pr", "create",
                        "--repo", target_repo,
                        "--base", default_branch,
                        "--head", f"{owner}:add-cortex",
                        "--title", pr_title,
                        "--body", pr_body
                    ],
                    cwd=clone_dir
                )
                compare_url = f"https://github.com/{target_repo}/compare/{default_branch}...{owner}:{fork_name}:add-cortex?expand=1"
                if code == 0:
                    print(f"[+] Opened PR on {target_repo}: {out}")
                else:
                    print(f"[+] Pushed fork branch {owner}/{fork_name}:add-cortex -> 1-Click PR Ready: {compare_url}")
            else:
                print(f"[*] {my_repo_url} already present in {target_repo}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Automated GitHub Repo Creator, SEO & Awesome-MCP PR Submitter")
    parser.add_argument("--repo-slug", default="Buzburg/cortex")
    parser.add_argument("--repo-url", default="https://github.com/Buzburg/cortex")
    parser.add_argument("--create-repo", action="store_true", help="Create and push public GitHub repo via gh CLI")
    parser.add_argument("--execute", action="store_true", help="Execute live gh CLI commands (default is dry-run)")
    args = parser.parse_args()

    dry = not args.execute
    if args.create_repo:
        create_and_push_repo(args.repo_slug, dry_run=dry)
    apply_github_seo_topics(args.repo_slug, dry_run=dry)
    if args.create_repo:
        create_github_release(args.repo_slug, dry_run=dry)
    for target in AWESOME_REPOS:
        submit_awesome_pr(target, args.repo_url, dry_run=dry)


if __name__ == "__main__":
    main()
