from __future__ import annotations

import pytest

from manual_cli import tracing


@pytest.fixture(autouse=True)
def _reset_tracing():
    tracing.reset()
    yield
    tracing.reset()
