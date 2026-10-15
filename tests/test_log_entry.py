from core.filter import LogFilter
from core.log_entry import entry_time, format_delta, message_key
from core.watch import WatchList

IOS = "Oct 15 16:04:18 iPhone-QA MyGame(UnityFramework)[2438] <Notice>: ping"
ISO = "2026-10-15 16:04:18 [LogType:Log] ping"


def test_entry_time_and_delta():
    assert entry_time("Oct 15 16:04:28 x") - entry_time(IOS) == 10
    assert entry_time("2026-10-15 16:05:18 x") - entry_time(ISO) == 60
    assert entry_time("no time here") is None
    assert [format_delta(s) for s in (0, 3, 65, 7260)] == ["", "+3с", "+1м05с", "+2ч01м"]


def test_message_key_ignores_time_only():
    assert message_key(IOS) == message_key(IOS.replace("16:04:18", "16:09:59"))
    assert message_key(IOS) != message_key(IOS.replace("ping", "pong"))
    assert message_key(ISO) == "[LogType:Log] ping"


def _entry(i, raw):
    return {"id": i, "raw": raw, "props": LogFilter().extract_props(raw)}


def test_watch_counts_any_spelling_and_remembers_last():
    watch = WatchList([("revenue OR adrevenue", True), ("level:error", False)])
    entries = [_entry(1, "Oct 15 16:00:00 g[1] <Notice>: ADREVENUE sent"),
               _entry(2, "Oct 15 16:00:01 g[1] <Notice>: af_ad_revenue {\"v\":1}"),
               _entry(3, "Oct 15 16:00:02 g[1] <Error>: boom")]
    assert watch.feed(entries) is True
    revenue, errors = watch.rules
    assert (revenue.count, revenue.last_entry_id) == (2, 2)
    assert errors.count == 0          # выключено
    errors.enabled = True
    watch.recount(entries)
    assert (revenue.count, errors.count) == (2, 1)
    assert watch.to_settings() == [["revenue OR adrevenue", True], ["level:error", True]]


def test_ios_time_uses_current_year_against_marker():
    from datetime import datetime
    now = datetime.now().replace(microsecond=0)
    month = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[now.month - 1]  # не strftime: Qt ставит локаль
    ios = f"{month} {now.day:2d} {now:%H:%M:%S} host p[1] <Notice>: x"
    marker = now.strftime("%Y-%m-%d %H:%M:%S") + " [LogDog:Marker] шаг"
    assert abs(entry_time(ios) - entry_time(marker)) < 1


def test_details_ignore_pid_and_take_body():
    from gui.widgets.side_panel import find_json, find_pairs
    from core.log_entry import message_body
    raw = 'Oct 15 16:04:01 iPhone-QA MyGame(UnityFramework)[2438] <Notice>: [X] a:1; b:2'
    assert find_json(message_body(raw)) is None
    assert find_pairs(message_body(raw)) == [("a", "1"), ("b", "2")]
    assert find_json('ev {"a": 1}') == {"a": 1}
