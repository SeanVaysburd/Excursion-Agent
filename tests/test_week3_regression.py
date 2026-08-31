"""P2 gate: the ported Week-3 retrieval module still produces its graded
checkpoint output, byte-for-byte on the deterministic blocks.

Blocks 1 (setup/query), 2 (retrieval trace) and 4 (cold start) are pure
functions of the committed corpus + embedding model, so they must match
docs/week3/expected_demo_output.txt exactly; block 3 (the rule-based
planner prose) is deliberately not compared, so a failure always names
the retrieval layer rather than formatting.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "docs" / "week3" / "expected_demo_output.txt"


def _blocks(text: str) -> dict[int, str]:
    sections: dict[int, list[str]] = {}
    current = 0
    for line in text.splitlines():
        if line.startswith("BLOCK "):
            try:
                current = int(line.split()[1].rstrip(",:"))
            except (IndexError, ValueError):
                current = 0
            sections[current] = []
        if current:
            sections.setdefault(current, []).append(line.rstrip())
    return {k: "\n".join(v) for k, v in sections.items()}


def test_week3_demo_reproduces_checkpoint_output(tmp_path):
    # Pinned to the 20-entry calibration snapshot: the live corpus grows
    # with real user feedback (by design), and the checkpoint bytes must
    # not depend on what the user logged last night.
    result = subprocess.run(
        [sys.executable, "-m", "scripts.week3.memory_demo",
         "--corpus", str(ROOT / "tests" / "fixtures" / "excursions_seed.json"),
         "--storage", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]

    actual = _blocks(result.stdout)
    expected = _blocks(EXPECTED.read_text())

    for block in (1, 2, 4):
        assert block in actual, f"BLOCK {block} missing from demo output"
        assert actual[block] == expected[block], (
            f"BLOCK {block} diverged from the committed Week-3 checkpoint "
            f"output, the port changed retrieval behavior"
        )

    # The load-bearing facts, asserted independently of formatting:
    assert "e02" in actual[2] and "e19" in actual[2], "expected corpus hits absent"
    assert "NO RELEVANT HISTORY" in actual[4], "cold start must be explicit"
