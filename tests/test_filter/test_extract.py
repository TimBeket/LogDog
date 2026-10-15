import pytest
from core.filter import LogFilter


@pytest.fixture
def f():
    return LogFilter()


def test_ios_syslog(f):
    props = f.extract_props('Jul 11 12:34:56 kernel[0] <Debug> system message')
    assert props["level"] == "debug"
    assert props["proc"] == "kernel"
    assert props["pid"] == "0"


def test_ios_syslog_info(f):
    props = f.extract_props('Jan  5 08:15:30 SpringBoard[1234] <Notice> app launched')
    assert props["level"] == "info"
    assert props["proc"] == "springboard"
    assert props["pid"] == "1234"


def test_ios_syslog_with_device_name(f):
    props = f.extract_props("Oct 15 14:02:11 iPhone-QA SpringBoard(FrontBoard)[58] <Notice>: Bootstrap")
    assert props["proc"] == "springboard(frontboard)"
    assert props["pid"] == "58"


def test_unity_style(f):
    props = f.extract_props('MyApp[5678] Some log message here')
    assert props["proc"] == "myapp"
    assert props["pid"] == "5678"


def test_no_pid_or_proc(f):
    props = f.extract_props('Just a standalone message')
    assert props["proc"] == ""
    assert props["pid"] == ""


def test_empty_string(f):
    props = f.extract_props("")
    assert props["raw"] == ""
    assert props["level"] == "info"
    assert props["proc"] == ""
    assert props["pid"] == ""
    assert props["text"] == ""


def test_multiline_block(f):
    block = "Jul 11 12:00:00 app[100] <Error> first line\ncontinuation line\nmore details"
    props = f.extract_props(block)
    assert props["level"] == "error"
    assert props["proc"] == "app"
    assert props["pid"] == "100"
    assert "continuation" in props["text"]
