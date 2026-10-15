"""The copy-paste commands in README.md and manual/ must parse in bash, zsh and fish.

CachyOS, one of the two distributions Ventulus is packaged for, uses fish as its
default shell, and the install steps were written for bash: a heredoc into
`sudo tee -a /etc/pacman.conf`, a `base=…` variable and a bracketed `(cd … &&
makepkg -si)` are all parse errors in fish, so a CachyOS user pasting the
documented install got an error at step 2. Nothing ran the commands in any shell
but bash.

Each fenced ``bash`` block is handed to the real shell in parse-only mode
(``fish --no-execute``, ``bash -n``, ``zsh -n``), so nothing is executed. A
shell that is not installed skips its cases; CI installs all three.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "manual").glob("*.md"))]
_FENCE = re.compile(r"^```(?:bash|sh|shell)\n(.*?)^```", re.MULTILINE | re.DOTALL)

PARSE_ONLY = {
    "bash": ["bash", "-n"],
    "zsh": ["zsh", "-n"],
    "fish": ["fish", "--no-execute"],
}


def _blocks() -> list[tuple[str, str]]:
    found = []
    for doc in DOCS:
        for i, match in enumerate(_FENCE.finditer(doc.read_text(encoding="utf-8"))):
            found.append((f"{doc.relative_to(ROOT).as_posix()}#{i}", match.group(1)))
    return found


BLOCKS = _blocks()


def _parse(shell: str, script: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is not installed")
    path = tmp_path / "block.sh"
    path.write_text(script, encoding="utf-8")
    return subprocess.run(
        [*PARSE_ONLY[shell], str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_the_install_blocks_are_collected() -> None:
    # The parse test below passes vacuously if the fence pattern stops matching.
    install = [code for name, code in BLOCKS if "pacman.conf" in code]
    assert install, "no block adding the repository to /etc/pacman.conf was found"
    assert any(name.startswith("README.md#") for name, _ in BLOCKS)
    assert any(name.startswith("manual/getting-started.md#") for name, _ in BLOCKS)


@pytest.mark.parametrize("shell", sorted(PARSE_ONLY))
@pytest.mark.parametrize(("name", "code"), BLOCKS, ids=[name for name, _ in BLOCKS])
def test_block_parses(shell: str, name: str, code: str, tmp_path: Path) -> None:
    result = _parse(shell, code, tmp_path)
    assert result.returncode == 0, f"{name} does not parse in {shell}:\n{result.stderr}"


# The bash-only forms the install steps used to contain. If the shell accepted
# them, the parse test above could not catch their return.
_BASH_ONLY = {
    "heredoc": "grep -q x /etc/pacman.conf || sudo tee -a /etc/pacman.conf <<'EOF'\n[x]\nEOF\n",
    "variable assignment": 'base=https://example.invalid\ncurl -fsSLO "$base/f"\n',
    "subshell in command position": "(cd packaging && makepkg -si)\n",
}


@pytest.mark.parametrize("form", sorted(_BASH_ONLY))
def test_fish_rejects_the_bash_only_forms(form: str, tmp_path: Path) -> None:
    assert _parse("bash", _BASH_ONLY[form], tmp_path).returncode == 0
    assert _parse("fish", _BASH_ONLY[form], tmp_path).returncode != 0
