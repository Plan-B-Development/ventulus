"""The shared diagnostic duration estimates (DEC-404 Stage 4 / DEC-408).

One copy of the arithmetic for every label that says how long a daemon
diagnostic takes. The session dialog's labels must come out byte-identical to
the literals they replaced, and the rounding must be the documented
quarter-minute one.
"""

from __future__ import annotations

import pytest

from ventulus.services import diagnostic_estimates as est


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (10, "~10 s"),
        (96, "~1½ min"),
        (240, "~4 min"),
        (63, "~1 min"),
        (78, "~1¼ min"),
        (264, "~4½ min"),
        (210, "~3½ min"),
    ],
)
def test_duration_text_rounds_to_quarter_minutes(seconds, text):
    assert est.duration_text(seconds) == text
