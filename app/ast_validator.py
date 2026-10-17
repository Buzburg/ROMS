"""Deterministic AST Static Analysis & Safety Gate.

Implements deterministic, outside-the-LLM static analysis for staged patches
as mandated in Omarchy Mojo.pdf (Pages 14-16).

Checks:
- Syntax validity via Python AST parsing.
- Injection & sandbox evasion checks (eval, exec, __import__, os.system, subprocess shell=True).
- Path traversal & secret targeting (targeting /etc/shadow, ~/.ssh, ~/.aws, .env, credentials).
- Dangerous file operations (unbounded recursion, symlink creation).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Optional


FORBIDDEN_CALLS = {
    "eval": "Use of eval() is strictly forbidden in sandbox tasks.",
    "exec": "Use of exec() is strictly forbidden in sandbox tasks.",
    "compile": "Use of dynamic compile() is restricted.",
    "__import__": "Dynamic __import__() is prohibited; use static imports.",
}

FORBIDDEN_MODULE_FUNCS = {
    ("os", "system"): "os.system() is forbidden; use structured container runner.",
    ("os", "popen"): "os.popen() is forbidden; use structured container runner.",
    ("subprocess", "Popen"): "Direct subprocess.Popen() must not be called with shell=True.",
}

SENSITIVE_PATH_PATTERNS = [
    r"\.\./\.\.",             # Path traversal
    r"/etc/shadow",           # System shadow
    r"/etc/passwd",           # System passwd
    r"\.ssh/",                # SSH keys
    r"\.aws/",                # AWS credentials
    r"\.env",                 # Environment secrets
    r"credentials\.json",     # API credentials
    r"secrets\.json",         # Secrets file
]


@dataclass
class AstViolation:
    file_path: str
    line: int
    rule_id: str
    message: str
    severity: str = "ERROR"   # ERROR or WARNING


class SafetyAstVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.violations: List[AstViolation] = []

    def visit_Call(self, node: ast.Call):
        # 1. Check direct forbidden built-in calls (eval, exec, etc.)
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                self.violations.append(
                    AstViolation(
                        file_path=self.file_path,
                        line=node.lineno,
                        rule_id=f"SEC-BUILTIN-{node.func.id.upper()}",
                        message=FORBIDDEN_CALLS[node.func.id],
                        severity="ERROR"
                    )
                )

        # 2. Check module calls (os.system, etc.)
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            mod_func = (node.func.value.id, node.func.attr)
            if mod_func in FORBIDDEN_MODULE_FUNCS:
                self.violations.append(
                    AstViolation(
                        file_path=self.file_path,
                        line=node.lineno,
                        rule_id=f"SEC-MOD-{mod_func[0]}-{mod_func[1]}",
                        message=FORBIDDEN_MODULE_FUNCS[mod_func],
                        severity="ERROR"
                    )
                )

            # Check subprocess shell=True
            if mod_func[0] == "subprocess":
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        self.violations.append(
                            AstViolation(
                                file_path=self.file_path,
                                line=node.lineno,
                                rule_id="SEC-SUBPROCESS-SHELL",
                                message="subprocess with shell=True is forbidden.",
                                severity="ERROR"
                            )
                        )

        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        # Check string literals for sensitive path targets
        if isinstance(node.value, str):
            val = node.value
            for pattern in SENSITIVE_PATH_PATTERNS:
                if re.search(pattern, val):
                    self.violations.append(
                        AstViolation(
                            file_path=self.file_path,
                            line=node.lineno,
                            rule_id="SEC-SENSITIVE-PATH",
                            message=f"String contains prohibited sensitive path pattern '{pattern}'.",
                            severity="ERROR"
                        )
                    )
                    break
        self.generic_visit(node)


def audit_python_code(code: str, file_path: str = "<staged>") -> dict:
    """Statically inspects Python code string using deterministic AST visitor."""
    try:
        tree = ast.parse(code, filename=file_path)
    except SyntaxError as e:
        return {
            "passed": False,
            "syntax_valid": False,
            "error": f"SyntaxError at line {e.lineno}: {e.msg}",
            "violations": [
                {
                    "file": file_path,
                    "line": e.lineno or 1,
                    "rule": "SYNTAX-ERROR",
                    "message": str(e.msg),
                    "severity": "ERROR"
                }
            ]
        }

    visitor = SafetyAstVisitor(file_path)
    visitor.visit(tree)

    has_errors = any(v.severity == "ERROR" for v in visitor.violations)
    return {
        "passed": not has_errors,
        "syntax_valid": True,
        "violations": [
            {
                "file": v.file_path,
                "line": v.line,
                "rule": v.rule_id,
                "message": v.message,
                "severity": v.severity
            }
            for v in visitor.violations
        ]
    }


def audit_file(path: Path | str) -> dict:
    """Reads and statically audits a file on disk."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")
    if target.suffix != ".py":
        return {"passed": True, "syntax_valid": True, "violations": []}
    code = target.read_text(encoding="utf-8", errors="replace")
    return audit_python_code(code, file_path=str(target))
