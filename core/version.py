"""
version.py — Application version manager & Git release controller.

Handles dynamic semantic versioning (starting at 1.0.01), version bumping,
Git commit & push operations, and setup bundle naming.
"""

import os
import re
import subprocess
import logging
from pathlib import Path
from typing import Dict, Tuple, Any

logger = logging.getLogger(__name__)

__version__ = "1.0.01"

VERSION_FILE = Path(__file__).resolve()
REPO_ROOT = VERSION_FILE.parent.parent


def get_version() -> str:
    """Return current application version string (e.g., '1.0.01')."""
    return __version__


def bump_version(increment_type: str = "patch") -> str:
    """
    Increment version string in core/version.py and return new version.
    Format: MAJOR.MINOR.PATCH (e.g. 1.0.01 -> 1.0.02)
    """
    global __version__
    parts = __version__.split(".")
    if len(parts) == 3:
        major, minor, patch = parts
        try:
            patch_int = int(patch) + 1
            new_patch = f"{patch_int:02d}" if len(patch) >= 2 else str(patch_int)
            new_version = f"{major}.{minor}.{new_patch}"
        except ValueError:
            new_version = __version__ + ".1"
    else:
        new_version = __version__ + ".1"

    # Update this file
    try:
        content = VERSION_FILE.read_text(encoding="utf-8")
        updated = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', f'__version__ = "{new_version}"', content)
        VERSION_FILE.write_text(updated, encoding="utf-8")
        __version__ = new_version
        logger.info("Bumped version to: %s", new_version)
    except Exception as exc:
        logger.error("Failed to save bumped version: %s", exc)

    return __version__


def get_git_info() -> Dict[str, Any]:
    """Retrieve Git repository status, branch name, and last commit hash."""
    info = {
        "is_git": False,
        "branch": "Main",
        "commit": "N/A",
        "clean": True,
        "has_remote": False,
        "message": ""
    }
    try:
        res = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and "true" in res.stdout:
            info["is_git"] = True

            # Get branch name
            b_res = subprocess.run(["git", "branch", "--show-current"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=3)
            info["branch"] = b_res.stdout.strip() or "main"

            # Get commit hash & msg
            c_res = subprocess.run(["git", "log", "-1", "--format=%h - %s (%cr)"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=3)
            info["commit"] = c_res.stdout.strip() or "Initial Commit"

            # Get status (dirty or clean)
            s_res = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=3)
            info["clean"] = len(s_res.stdout.strip()) == 0

            # Get remote URL
            r_res = subprocess.run(["git", "remote", "-v"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=3)
            info["has_remote"] = len(r_res.stdout.strip()) > 0
    except Exception as exc:
        info["message"] = str(exc)

    return info


def git_commit_and_push(commit_message: str, push_remote: bool = True) -> Tuple[bool, str]:
    """
    Stage all changes, create a Git commit with the provided message,
    and optionally push to the configured remote repository.
    """
    try:
        # Add all
        add_res = subprocess.run(["git", "add", "."], cwd=REPO_ROOT, capture_output=True, text=True, timeout=15)
        if add_res.returncode != 0:
            return False, f"Git add hatası: {add_res.stderr}"

        # Commit
        msg = commit_message.strip() or f"v{get_version()} güncellemeleri ve geliştirmeler"
        commit_res = subprocess.run(["git", "commit", "-m", msg], cwd=REPO_ROOT, capture_output=True, text=True, timeout=15)
        if commit_res.returncode != 0 and "nothing to commit" not in commit_res.stdout.lower():
            return False, f"Git commit hatası: {commit_res.stderr}"

        push_msg = ""
        if push_remote:
            push_res = subprocess.run(["git", "push"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
            if push_res.returncode == 0:
                push_msg = " ve uzak sunucuya (Remote Push) başarıyla gönderildi."
            else:
                push_msg = f" (Local commit başarılı ancak push uyarısı: {push_res.stderr.strip()[:80]})"
        
        return True, f"✅ Git Commit tamamlandı: '{msg}'{push_msg}"
    except Exception as exc:
        return False, f"Git işlemi başarısız: {exc}"
