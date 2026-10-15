import pytest
from PySide6.QtCore import QTimer
from core.filter import LogFilter
from core.processor import LogProcessor, is_new_log_line, group_lines


@pytest.fixture
def filter_all():
    f = LogFilter()
    f.set_filter("")
    return f


@pytest.fixture
def filter_error_only():
    f = LogFilter()
    f.set_filter("level:error")
    return f


@pytest.fixture
def processor(qapp, filter_all):
    p = LogProcessor(filter_all)
    yield p
    if p.isRunning():
        p.stop()
        p.quit()
        p.wait(2000)


def test_is_new_log_line_ios_date(processor):
    assert processor._is_new_log_line("Jul 11 12:00:00 kernel[0] msg") is True
    assert processor._is_new_log_line("Jan  5 08:15:30 app[123] msg") is True


def test_is_new_log_line_iso_date(processor):
    assert processor._is_new_log_line("2024-01-01 12:00:00 something") is True


def test_is_new_log_line_continuation(processor):
    assert processor._is_new_log_line("    continuation line") is False
    assert processor._is_new_log_line("regular text without date") is False
    assert processor._is_new_log_line("") is False


def test_processor_routes_lines_to_signal(qtbot, processor):
    results = []
    processor.processed_blocks.connect(lambda blocks: results.extend(blocks))
    processor.start()

    with qtbot.waitSignal(processor.processed_blocks, timeout=2000):
        processor.enqueue_lines(["Jul 11 12:00:00 test[1] <Info> hello"])

    processor.stop()
    processor.quit()
    processor.wait(2000)

    assert len(results) == 1
    assert "hello" in results[0]["raw"]
    assert results[0]["props"]["level"] == "info"


def test_multiline_block_groups_together(qtbot, processor):
    results = []
    processor.processed_blocks.connect(lambda blocks: results.extend(blocks))
    processor.start()

    with qtbot.waitSignal(processor.processed_blocks, timeout=2000):
        processor.enqueue_lines([
            "Jul 11 12:00:00 app[1] <Error> first line",
            "continuation",
            "more details",
        ])

    processor.stop()
    processor.quit()
    processor.wait(2000)

    assert len(results) == 1
    assert "continuation" in results[0]["raw"]
    assert "more details" in results[0]["raw"]


def test_processor_emits_all_blocks(qtbot, qapp, filter_error_only):
    """Processor no longer filters — all blocks pass through regardless of filter."""
    processor = LogProcessor(filter_error_only)
    results = []
    processor.processed_blocks.connect(lambda blocks: results.extend(blocks))
    processor.start()

    with qtbot.waitSignal(processor.processed_blocks, timeout=2000):
        processor.enqueue_lines([
            "Jul 11 12:00:00 app[1] <Info> should pass through",
        ])

    processor.stop()
    processor.quit()
    processor.wait(2000)

    assert len(results) == 1
    assert results[0]["props"]["level"] == "info"


def test_filter_passes_error(qtbot, qapp, filter_error_only):
    processor = LogProcessor(filter_error_only)
    results = []
    processor.processed_blocks.connect(lambda blocks: results.extend(blocks))
    processor.start()

    with qtbot.waitSignal(processor.processed_blocks, timeout=2000):
        processor.enqueue_lines(["Jul 11 12:00:00 app[1] <Error> real error"])

    processor.stop()
    processor.quit()
    processor.wait(2000)

    assert len(results) == 1
    assert results[0]["props"]["level"] == "error"


def test_group_lines_single_group_with_continuations():
    groups = group_lines(["Jul 11 12:00:00 a", "cont1", "cont2"])
    assert groups == [["Jul 11 12:00:00 a", "cont1", "cont2"]]


def test_group_lines_multiple_groups_no_duplication():
    groups = group_lines([
        "Jul 11 12:00:00 a",
        "cont1",
        "Jul 11 12:00:01 b",
        "Jul 11 12:00:02 c",
    ])
    assert len(groups) == 3
    assert groups[0] == ["Jul 11 12:00:00 a", "cont1"]
    assert groups[1] == ["Jul 11 12:00:01 b"]
    assert groups[2] == ["Jul 11 12:00:02 c"]


def test_group_lines_drops_blank_lines():
    groups = group_lines(["Jul 11 12:00:00 a", "", "  ", "cont"])
    assert groups == [["Jul 11 12:00:00 a", "cont"]]


def test_group_lines_leading_continuation_starts_its_own_group():
    groups = group_lines(["orphan continuation", "Jul 11 12:00:00 a"])
    assert groups == [["orphan continuation"], ["Jul 11 12:00:00 a"]]


def test_is_new_log_line_module_function():
    assert is_new_log_line("Jul 11 12:00:00 x") is True
    assert is_new_log_line("2024-01-01 12:00:00 x") is True
    assert is_new_log_line("not a new line") is False


def test_multiple_entries_in_one_batch_not_duplicated(qtbot, processor):
    """Regression for a bug where every block but the last in a batch was
    emitted twice (once when created, once when the next new-line event
    finalized it)."""
    results = []
    processor.processed_blocks.connect(lambda blocks: results.extend(blocks))
    processor.start()

    with qtbot.waitSignal(processor.processed_blocks, timeout=2000):
        processor.enqueue_lines([
            "2024-01-01 12:00:00 first entry",
            "continuation of first",
            "2024-01-01 12:00:01 second entry",
            "2024-01-01 12:00:02 third entry",
        ])

    processor.stop()
    processor.quit()
    processor.wait(2000)

    assert len(results) == 3
    raws = [r["raw"] for r in results]
    assert raws[0] == "2024-01-01 12:00:00 first entry\ncontinuation of first"
    assert raws[1] == "2024-01-01 12:00:01 second entry"
    assert raws[2] == "2024-01-01 12:00:02 third entry"



