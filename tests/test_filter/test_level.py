import pytest
from core.filter import get_log_level


def test_xml_tag_error():
    assert get_log_level("<error> something broke") == "error"


def test_xml_tag_warning():
    assert get_log_level("<warning> check this") == "warn"


def test_xml_tag_warn():
    assert get_log_level("<warn> check this") == "warn"


def test_xml_tag_debug():
    assert get_log_level("<debug> verbose stuff") == "debug"


def test_xml_tag_notice():
    assert get_log_level("<notice> informative") == "info"


def test_xml_tag_fault():
    assert get_log_level("<fault> hardware issue") == "error"


def test_error_keyword_exception():
    assert get_log_level("NullReferenceException at Foo.Bar()") == "error"


def test_error_keyword_crash():
    assert get_log_level("App crashed with signal 11") == "error"


def test_error_keyword_fatal():
    assert get_log_level("Fatal error in render") == "error"


def test_warning_keyword():
    assert get_log_level("this is a warning message") == "warn"


def test_tag_not_recognized_defaults_to_keyword():
    assert get_log_level("<info> something error happened") == "error"


def test_applovin_exception_debug():
    assert get_log_level("Debug [AppLovin MAX] init") == "debug"
    assert get_log_level("[ALSdk] Debug: starting") == "debug"


def test_empty_string():
    assert get_log_level("") == "info"


def test_no_tags_or_keywords():
    assert get_log_level("Jul 11 12:00:00 kernel[0] regular message") == "info"


def test_case_insensitive_tags():
    assert get_log_level("<ERROR> uppercase") == "error"
    assert get_log_level("<Warning> mixed case") == "warn"


def test_none_input():
    assert get_log_level(None) == "info"


# ====================== НОВЫЕ ТЕСТЫ ======================

# --- Unity LogType ---

def test_unity_logtype_error():
    assert get_log_level("[LogType:Error] NullReferenceException") == "error"


def test_unity_logtype_warning():
    assert get_log_level("[LogType:Warning] audio missing") == "warn"


def test_unity_logtype_log():
    assert get_log_level("[LogType:Log] game started") == "info"


def test_unity_logtype_assert():
    assert get_log_level("[LogType:Assert] condition failed") == "error"


def test_unity_logtype_exception():
    assert get_log_level("[LogType:Exception] something broke") == "error"


def test_unity_logtype_debug():
    assert get_log_level("[LogType:Debug] verbose") == "debug"


def test_unity_logtype_case_insensitive():
    assert get_log_level("[logtype:error] case") == "error"


# --- C# Exception suffix ---

def test_csharp_exception_missing_reference():
    assert get_log_level("MissingReferenceException: blah") == "error"


def test_csharp_exception_invalid_operation():
    assert get_log_level("InvalidOperationException at Foo()") == "error"


def test_csharp_exception_argument_null():
    assert get_log_level("ArgumentNullException: blah") == "error"


def test_csharp_exception_any_suffix():
    assert get_log_level("CustomGameException: something") == "error"


# --- Bracket / Paren / Pipe markers ---

def test_bracket_error():
    assert get_log_level("[Error] something broke") == "error"
    assert get_log_level("[ERR] short") == "error"


def test_bracket_warning():
    assert get_log_level("[WARNING] check this") == "warn"
    assert get_log_level("[WARN] check this") == "warn"


def test_bracket_info():
    assert get_log_level("[INFO] just info") == "info"


def test_bracket_debug():
    assert get_log_level("[DEBUG] verbose") == "debug"


def test_paren_error():
    assert get_log_level("(Error) something") == "error"


def test_pipe_error():
    assert get_log_level("|ERROR| something") == "error"


def test_bracket_fatal():
    assert get_log_level("[FATAL] system halt") == "error"


def test_bracket_critical():
    assert get_log_level("[CRITICAL] failure") == "error"


# --- Colon-prefix markers ---

def test_colon_prefix_error():
    assert get_log_level("ERROR: something broke") == "error"


def test_colon_prefix_fatal():
    assert get_log_level("FATAL: system halt") == "error"


def test_colon_prefix_warning():
    assert get_log_level("WARNING: check this") == "warn"
    assert get_log_level("WARN: check this") == "warn"


# --- Syslog numeric priority ---

def test_syslog_numeric_emerg():
    assert get_log_level("<0> Jul 11 emergency") == "error"


def test_syslog_numeric_alert():
    assert get_log_level("<1> Jul 11 alert") == "error"


def test_syslog_numeric_crit():
    assert get_log_level("<2> Jul 11 critical") == "error"


def test_syslog_numeric_error():
    assert get_log_level("<3> Jul 11 error msg") == "error"


def test_syslog_numeric_warning():
    assert get_log_level("<4> Jul 11 warning msg") == "warn"


def test_syslog_numeric_notice():
    assert get_log_level("<5> Jul 11 notice msg") == "info"


def test_syslog_numeric_info():
    assert get_log_level("<6> Jul 11 info msg") == "info"


def test_syslog_numeric_debug():
    assert get_log_level("<7> Jul 11 debug msg") == "debug"


# --- Word boundary fixes ---

def test_word_boundary_avoid_false_positive():
    assert get_log_level("OnInterstitialAdLoadFailedEvent happened") != "error"


def test_word_boundary_failed_caught():
    assert get_log_level("Failed to connect to server") == "error"


def test_word_boundary_error_word():
    assert get_log_level("There was an error") == "error"


def test_word_boundary_errors_word():
    assert get_log_level("Found 2 errors") == "error"


# --- Fault keyword ---

def test_fault_keyword_outside_tag():
    assert get_log_level("kernel fault occurred") == "error"


# --- Debug standalone ---

def test_debug_standalone_word():
    assert get_log_level("Debug [AppLovin MAX] init fallback") == "debug"


def test_debug_not_log_dot():
    assert get_log_level("Debug.LogError test") != "debug"


def test_debug_not_handler():
    assert get_log_level("UnityEngine.DebugLogHandler") != "debug"


# --- XML tag <info> ---

def test_xml_tag_info_recognized():
    assert get_log_level("<info> just a message") == "info"


# --- Stack trace alone stays info (Unity attaches stack traces to all levels) ---

def test_stack_trace_alone_stays_info():
    block = "Some log message\n  at Foo.Bar() [0x00000] in <abcdef>:0"
    assert get_log_level(block) == "info"


def test_debughandler_stays_info():
    block = "UnityEngine.DebugLogHandler:Internal_Log(LogType, LogOption, String, Object)"
    assert get_log_level(block) == "info"


# --- Keywords override info/debug markers (fewer false negatives) ---

def test_bracket_info_keyword_still_caught():
    assert get_log_level("[INFO] an error occurred") == "error"


def test_bracket_debug_keyword_still_caught():
    assert get_log_level("[DEBUG] error check complete") == "error"


# --- LogDog:System tag (highest priority) ---

def test_system_tag_detected():
    assert get_log_level("[LogDog:System] Соединение потеряно") == "system"


def test_system_tag_short_form_detected():
    assert get_log_level("2026-08-16 10:00:00 [System] Соединение потеряно") == "system"


def test_system_tag_case_insensitive():
    assert get_log_level("[logdog:system] test") == "system"


def test_system_tag_beats_error_keyword():
    assert get_log_level("[LogDog:System] Error: something failed") == "system"


# --- LogType shadowing fix (Unity LogType no longer shadows a real exception) ---

def test_logtype_log_overridden_by_exception():
    assert get_log_level("[LogType:Log] NullReferenceException thrown") == "error"


def test_logtype_info_overridden_by_error_keyword():
    assert get_log_level("[LogType:Info] critical failure detected") == "error"


def test_logtype_warning_unchanged():
    assert get_log_level("[LogType:Warning] audio missing") == "warn"


def test_logtype_log_stays_info_without_stronger_signal():
    assert get_log_level("[LogType:Log] game started") == "info"


def test_logtype_debug_stays_debug_without_stronger_signal():
    assert get_log_level("[LogType:Debug] verbose") == "debug"


# --- Consolidated GUI keyword signals, now part of the canonical heuristic ---

def test_assertion_keyword():
    assert get_log_level("Assertion failed: index out of range") == "error"


def test_nullreference_bare_keyword():
    assert get_log_level("nullreference caught silently") == "error"


# --- Numeric syslog priority anchored to block start ---

def test_numeric_priority_not_anchored_no_false_positive():
    assert get_log_level("Player achieved level <3> in the game") == "info"


def test_numeric_priority_still_anchored_with_leading_whitespace():
    assert get_log_level("   <3> indented priority message") == "error"


# --- Case-insensitive colon markers ---

def test_colon_prefix_error_lowercase():
    assert get_log_level("error: lowercase should match") == "error"


def test_colon_prefix_warning_lowercase():
    assert get_log_level("warn: lowercase should match") == "warn"


def test_colon_prefix_debug_lowercase():
    assert get_log_level("debug: verbose trace") == "debug"
