"""Shared pytest setup for medtrics-qa-automation.

Lives at the plugin root so pytest auto-loads it for tests anywhere in
skills/*/tests/. Centralizes the sys.path inserts so individual test files
can do plain `import parse_checklist_steps as P` instead of repeating
boilerplate.

Discovery rule: every directory matching skills/*/scripts/ and
skills/*/scripts/lib/ is prepended to sys.path. Module names across the
plugin are unique by convention, so insertion order doesn't matter.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _script_dirs() -> list[Path]:
    out: list[Path] = []
    skills = ROOT / "skills"
    if not skills.is_dir():
        return out
    for skill in skills.iterdir():
        if not skill.is_dir():
            continue
        scripts = skill / "scripts"
        if scripts.is_dir():
            out.append(scripts)
            lib = scripts / "lib"
            if lib.is_dir():
                out.append(lib)
    return out


for _p in _script_dirs():
    _p_str = str(_p)
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)
