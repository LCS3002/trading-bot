"""The signal, sizing and routing logic must import without Alpaca credentials.

This is the invariant that makes the rest of the suite possible, so it gets asserted
directly rather than left as an implicit consequence of the other tests passing.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_require_credentials_raises_when_keys_are_missing(monkeypatch):
    monkeypatch.setattr(config, "ALPACA_API_KEY", "")
    monkeypatch.setattr(config, "ALPACA_SECRET_KEY", "")

    with pytest.raises(RuntimeError, match="Missing Alpaca credentials"):
        config.require_credentials()


def test_require_credentials_passes_when_keys_are_present(monkeypatch):
    monkeypatch.setattr(config, "ALPACA_API_KEY", "key")
    monkeypatch.setattr(config, "ALPACA_SECRET_KEY", "secret")

    config.require_credentials()  # must not raise


@pytest.mark.skipif(
    (REPO_ROOT / ".env").exists(),
    reason="a local .env is loaded by python-dotenv, so credentials cannot be isolated",
)
def test_every_module_imports_with_no_credentials_in_the_environment(tmp_path):
    """Run from a scratch directory with the credential variables stripped out.

    Also asserts the Alpaca clients are still unbuilt after import — lazy construction
    is what keeps the pure logic testable, so a module-level client would be a
    regression even if the import itself happened to succeed.
    """
    script = (
        "import config, data, indicators, risk, strategy, execution\n"
        "assert data._client is None, 'data built a client at import'\n"
        "assert risk._trading_client is None, 'risk built a client at import'\n"
        "assert execution._trading_client is None, 'execution built a client at import'\n"
        "print('ok')\n"
    )

    env = {k: v for k, v in os.environ.items() if k not in ("API_KEY", "SECRET_KEY")}
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "ok" in result.stdout


def test_indicators_has_no_heavy_native_dependency():
    """indicators.py is deliberately numpy/pandas only — pulling pandas-ta back in would
    re-pin the project to Python 3.12-3.13 via numba."""
    source = (REPO_ROOT / "indicators.py").read_text(encoding="utf-8")

    assert "pandas_ta" not in source
    assert "import numpy" in source
