from datetime import datetime

from utils.helpers import log_file_name

WHEN = datetime(2026, 11, 11, 9, 5)


def test_name_has_source_date_and_time():
    assert log_file_name("iPhone QA", WHEN) == "LogDog_iPhone-QA_2026-11-11_09-05.log"


def test_without_source():
    assert log_file_name("", WHEN) == "LogDog_2026-11-11_09-05.log"
    assert log_file_name('  :*? ', WHEN) == "LogDog_2026-11-11_09-05.log"


def test_characters_windows_forbids_are_removed():
    assert log_file_name('Семён\'s iPhone: "test" <1>/2\\3|4?*', WHEN) == \
        "LogDog_Семён's-iPhone-test-1234_2026-11-11_09-05.log"


def test_long_source_is_cut():
    name = log_file_name("x" * 200, WHEN)
    assert name == "LogDog_" + "x" * 40 + "_2026-11-11_09-05.log"
