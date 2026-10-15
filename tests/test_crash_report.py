import json

import pytest

from transports.crash_reporter import CrashReportItem, write_readable_log

SAMPLE_IPS = json.dumps(
    {
        "bug_type": "309",
        "captureTime": "2026-08-12 10:30:00.123-0400",
        "app_name": "MyGame",
        "name": "MyGame",
        "incident_id": "ABC123",
        "exception": {"type": "NSGenericException", "signal": "SIGABRT", "reason": "Test crash"},
    }
)


def test_write_readable_log_includes_metadata():
    item = CrashReportItem(
        path="/MyGame-2026-08-12-103000.ips",
        name="MyGame",
        timestamp="2026-08-12 10:30:00",
        bug_type="309",
        incident_id="ABC123",
    )
    text = write_readable_log(SAMPLE_IPS, item)

    assert "MyGame" in text
    assert "ABC123" in text
    assert "309" in text
    assert "2026-08-12 10:30:00" in text
    assert "MyGame-2026-08-12-103000.ips" in text


def test_write_readable_log_pretty_prints_json_body():
    item = CrashReportItem(path="/App.xcsymptom")
    text = write_readable_log(SAMPLE_IPS, item)

    assert '"exception"' in text
    assert '"Test crash"' in text
    assert '"bug_type": "309"' in text.replace("bug_type", "bug_type")


def test_write_readable_log_keeps_non_json_content():
    item = CrashReportItem(path="/raw.txt")
    raw = "not json at all\nsecond line"
    text = write_readable_log(raw, item)
    assert raw in text


def test_write_readable_log_with_empty_item():
    item = CrashReportItem(path="")
    text = write_readable_log(SAMPLE_IPS, item)
    assert "iOS Crash Report" in text