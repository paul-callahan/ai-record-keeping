import pytest

from claude_daily_summary.config import _local_timezone


def test_tz_env_var_wins(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Berlin")
    assert _local_timezone().key == "Europe/Berlin"


def test_unknown_tz_env_var_aborts(monkeypatch):
    monkeypatch.setenv("TZ", "Not/AZone")
    with pytest.raises(SystemExit, match="unknown timezone"):
        _local_timezone()


def test_system_timezone_fallback(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    assert _local_timezone().key  # macOS: resolved from /etc/localtime
