import re
from typing import List, Tuple
from utils.logger import logger

# ==================== Exceptions / Level detection ====================
LEVEL_EXCEPTIONS = {
    "debug": [
        r"Debug\s*\[(?:AppLovin MAX|AppLovinSdk|ALSdk[^\]]*)\]",
        r"\[(?:AppLovin MAX|AppLovinSdk|ALSdk[^\]]*)\]\s*Debug",
        r"DEBUG\s*\[(?:AppLovinSdk|ALSdk[^\]]*)\]",
    ],
    "error": [],
    "warn": [],
    "info": [],
}

def add_exception(level: str, pattern: str):
    """Добавляет шаблон исключения для определенного уровня лога."""
    LEVEL_EXCEPTIONS.setdefault(level.lower(), []).append(pattern)
    _compiled_exceptions.clear()


# Определение уровня — на каждую строку лога (iPhone шлёт тысячи в секунду),
# поэтому выражения скомпилированы заранее, а выражения одного шага собраны в
# одно: раньше это были ~40 отдельных re.search на строку, и медленный
# компьютер не успевал за потоком логов.
_compiled_exceptions: dict = {}


def _exception_patterns():
    if not _compiled_exceptions:
        for level, patterns in LEVEL_EXCEPTIONS.items():
            if patterns:
                _compiled_exceptions[level] = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    return _compiled_exceptions.items()


_SYSTEM_RE = re.compile(r'\[(?:LogDog:)?System\]', re.IGNORECASE)
_LOGTYPE_RE = re.compile(r'\[LogType:\s*(\w+)\]', re.IGNORECASE)
_EXCEPTION_RE = re.compile(r'\b\w*[Ee]xception\b')
_PRIORITY_RE = re.compile(r'^\s*<([0-7])>')
_ERROR_MARKER_RE = re.compile(r'[\[\(|](?:error|err|fatal|critical)[\]\)|]|(?:^|\s)(?:ERROR|FATAL|CRITICAL)\s*:',
                              re.IGNORECASE)
_WARN_MARKER_RE = re.compile(r'[\[\(|](?:warn(?:ing)?)[\]\)|]|(?:^|\s)(?:WARN(?:ING)?)\s*:', re.IGNORECASE)
_TAG_RE = re.compile(r'<\s*([A-Za-z]+)\s*>')
_ERROR_WORDS_RE = re.compile("|".join([
    r'\berrors?\b',
    r'\bfailed\b',
    r'\bfailure\b',
    r'\bfatal\b',
    r'\bassert(?:ion)?\b',
    r'\bcritical\b',
    r'\bcrash(?:es|ed|ing)?\b',
    r'\bfault\b',
    r'\binvalid\b',
    r'\bunable\b',
    r'\bcannot\b',
    r'\btimeout\b',
    r'\babort(?:ed|ing)?\b',
    r'\bsegfault\b',
    r'\bunhandled\b',
    r'\buncaught\b',
    r'\bstack\s?trace\b',
    r'\b(?:not\s+found)\b',
    r'\b(?:out\s+of\s+(?:range|memory|bounds))\b',
    r'\bnullreference\b',
]))
_WARN_WORDS_RE = re.compile(r'\bwarn(?:ing)?\b|\bobsolete\b|\bdeprecated\b')
_INFO_MARKER_RE = re.compile(r'[\[\(|](?:info)[\]\)|]|(?:^|\s)(?:INFO)\s*:', re.IGNORECASE)
# \bDebug\b(?!\.) — защитный вариант: не ловит Debug.Log* / DebugLogHandler
_DEBUG_MARKER_RE = re.compile(r'[\[\(|](?:debug)[\]\)|]|(?:^|\s)(?:DEBUG)\s*:|\bDebug\b(?!\.)', re.IGNORECASE)
_LOGTYPE_MAP = {
    'error': 'error', 'err': 'error', 'fatal': 'error', 'critical': 'error',
    'exception': 'error', 'assert': 'error',
    'warning': 'warn', 'warn': 'warn',
    'log': 'info', 'info': 'info',
    'debug': 'debug',
}


def get_log_level(block: str) -> str:
    """Определяет уровень лога по содержимому блока.

    Многоуровневая эвристика для Unity-логов на iOS.
    Обрабатывает общие форматы: [LogType:*], C# *Exception,
    [ERROR] / (WARN) / |INFO| / FATAL: / <error> / <0-7> числовые приоритеты syslog,
    XML-теги, и ключевые слова с границами слов.
    """
    if not block:
        return "info"
    tentative = None

    # 0. Служебные сообщения LogDog о состоянии соединения — наивысший приоритет,
    # не должны попадать под обычную эвристику ошибок/предупреждений.
    if _SYSTEM_RE.search(block):
        return 'system'

    # 1. AppLovin исключения (существующие)
    for level, pattern in _exception_patterns():
        if pattern.search(block):
            return level

    # 2. Unity LogType: [LogType:Error], [LogType:Warning], [LogType:Log], ...
    lt = _LOGTYPE_RE.search(block)
    if lt:
        mapped = _LOGTYPE_MAP.get(lt.group(1).lower(), 'info')
        if mapped == 'error':
            return mapped
        # Не error-типы — только предварительный результат: более сильный сигнал
        # (например C#-исключение ниже) должен иметь возможность его переопределить.
        tentative = mapped

    # 3. C# *Exception suffix — ЛЮБОЙ тип исключения
    if _EXCEPTION_RE.search(block):
        return 'error'

    # 4. Числовой syslog приоритет <0>-<7>, привязан к началу строки
    num_tag = _PRIORITY_RE.match(block)
    if num_tag:
        p = int(num_tag.group(1))
        if p <= 3:
            return 'error'
        elif p == 4:
            return 'warn'
        elif p == 7:
            return 'debug'

    # 5–6. Явные маркеры: [ERROR] (ERROR) |ERROR| ERROR: / FATAL: / CRITICAL:, то же для WARN
    if _ERROR_MARKER_RE.search(block):
        return 'error'
    if _WARN_MARKER_RE.search(block):
        return 'warn'

    # 7. XML-теги (существующие + <info>)
    tags = [t.lower() for t in _TAG_RE.findall(block)]
    for t in tags:
        if t in ('error', 'fault'):
            return 'error'

    for t in tags:
        if t in ('warning', 'warn'):
            tentative = 'warn'
        if t == 'debug':
            tentative = tentative or 'debug'
        if t in ('notice', 'info'):
            tentative = tentative or 'info'

    # 8–9. Ключевые слова ошибок и предупреждений с границами слов
    text = block.lower()
    if _ERROR_WORDS_RE.search(text):
        return 'error'
    if _WARN_WORDS_RE.search(text):
        return 'warn'

    # 10–11. Явные маркеры info/debug — только предварительно
    if not tentative:
        if _INFO_MARKER_RE.search(block):
            tentative = 'info'
        elif _DEBUG_MARKER_RE.search(block):
            tentative = 'debug'

    # 12. Tentative
    if tentative:
        return tentative

    # 13. Fallback
    return 'info'

# ==================== Filter ====================
FIELDS = ("level", "proc", "pid", "text")
LEVEL_VALUES = ("error", "warn", "info", "debug")
LEVEL_ALIASES = {"e": "error", "error": "error", "err": "error",
                 "w": "warn", "warning": "warn", "warn": "warn",
                 "i": "info", "info": "info", "d": "debug", "debug": "debug"}
OPERATORS = ("AND", "OR", "NOT")


def _is_word(s: str, i: int, word: str) -> bool:
    """Оператор — слово целиком (без учёта регистра), за ним пробел, скобка или конец."""
    end = i + len(word)
    return s[i:end].upper() == word and (end == len(s) or s[end].isspace() or s[end] in '()')


def tokenize_with_positions(s: str) -> List[Tuple[str, int, int]]:
    """Токены фильтра с позициями (текст, начало, конец). Одна функция и для
    LogFilter, и для подсветки в поле фильтра (core.filter_syntax) — чтобы
    подсветка не расходилась с тем, что реально ищется."""
    tokens = []
    i = 0
    while i < len(s):
        if s[i].isspace():
            i += 1
            continue
        if s[i] in '()':
            tokens.append((s[i], i, i + 1))
            i += 1
            continue
        if s[i] in ('"', "'"):
            j = s.find(s[i], i + 1)
            end = len(s) if j == -1 else j + 1  # незакрытая кавычка — до конца строки
            tokens.append((s[i:end], i, end))
            i = end
            continue
        word = next((w for w in OPERATORS if _is_word(s, i, w)), None)
        if word:
            tokens.append((word, i, i + len(word)))
            i += len(word)
            continue
        # Скобка, приклеенная к слову, — часть слова: имена процессов iOS
        # выглядят как «MyGame(UnityFramework)», и proc:mygame(UnityFramework)
        # должно искать этот процесс, а не «proc:mygame AND (UnityFramework)».
        # Группа условий — скобка в начале токена: «(level:error OR …)».
        j = i
        depth = 0
        while j < len(s) and not s[j].isspace():
            if s[j] in ('"', "'"):
                k = s.find(s[j], j + 1)
                if k == -1:
                    break
                j = k + 1
                continue
            if s[j] == '(':
                depth += 1
            elif s[j] == ')':
                if depth == 0:
                    break  # закрывает группу, а не слово
                depth -= 1
            j += 1
        tokens.append((s[i:j], i, j))
        i = j
    return tokens


def _ends_operand(token: str) -> bool:
    return token == ')' or (token not in ('(',) and token.upper() not in OPERATORS)


def _starts_operand(token: str) -> bool:
    return token == '(' or token.upper() == 'NOT' or token.upper() not in OPERATORS and token != ')'


def with_implicit_and(tokens: List[str]) -> List[str]:
    """`Failed to fetch` = `Failed AND to AND fetch`. Без этого из нескольких
    слов подряд учитывалось только последнее (RPN оставлял на стеке его)."""
    result: List[str] = []
    for token in tokens:
        if result and _ends_operand(result[-1]) and _starts_operand(token):
            result.append('AND')
        result.append(token)
    return result
class LogFilter:
    """Фильтрует лог-сообщения по заданным критериям (RPN)."""
    
    def __init__(self):
        """Инициализирует пустой фильтр."""
        self.filter_text = ""
        self.tokens: List[str] = []
        self.rpn: List[str] = []

    def set_filter(self, filter_text: str):
        """Устанавливает текст фильтра и преобразует его в обратную польскую нотацию."""
        self.filter_text = filter_text.strip()
        logger.debug("LogFilter.set_filter: %s", self.filter_text)
        if self.filter_text:
            try:
                self.tokens = self._tokenize(self.filter_text)
                self.rpn = self._to_rpn(self.tokens)
            except Exception as e:
                logger.exception("Failed to parse filter: %s", e)
                self.tokens = []
                self.rpn = []
        else:
            self.tokens = []
            self.rpn = []

    def _tokenize(self, s: str) -> List[str]:
        return [text for text, _, _ in tokenize_with_positions(s)]

    def _to_rpn(self, tokens: List[str]) -> List[str]:
        prec = {'NOT':3,'AND':2,'OR':1}
        out = []
        stack = []
        for t in with_implicit_and(tokens):
            up = t.upper()
            if up in ('AND','OR','NOT'):
                while stack and stack[-1] != '(' and prec.get(stack[-1].upper(),0) >= prec[up]:
                    out.append(stack.pop())
                stack.append(up)
            elif t == '(':
                stack.append(t)
            elif t == ')':
                while stack and stack[-1] != '(':
                    out.append(stack.pop())
                if stack and stack[-1] == '(':
                    stack.pop()
            else:
                out.append(t)
        while stack:
            out.append(stack.pop())
        return out

    def _unquote(self, s: str) -> str:
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        return s

    def match(self, block_or_props) -> bool:
        if not self.filter_text:
            return True
        if not self.rpn:
            return True
        if isinstance(block_or_props, dict):
            props = block_or_props
        else:
            props = self._extract_props_from_block(block_or_props)
        try:
            res = self._eval_rpn(self.rpn, props)
            return res
        except Exception:
            return True

    def _eval_rpn(self, rpn: List[str], props: dict) -> bool:
        stack: List[bool] = []
        for token in rpn:
            up = token.upper()
            if up == 'AND':
                b = stack.pop() if stack else False
                a = stack.pop() if stack else False
                stack.append(a and b)
            elif up == 'OR':
                b = stack.pop() if stack else False
                a = stack.pop() if stack else False
                stack.append(a or b)
            elif up == 'NOT':
                a = stack.pop() if stack else False
                stack.append(not a)
            else:
                res = self._match_operand(token, props)
                stack.append(res)
        return stack[-1] if stack else True

    def _match_operand(self, operand: str, props: dict) -> bool:
        operand = operand.strip()
        if not operand:
            return True
        fld, sep, val = operand.partition(':')
        fld = fld.strip().lower()
        if not sep or fld not in FIELDS:
            # Не поле фильтра — ищем текст целиком, с двоеточием:
            # `Exception:`, `http://host`, `"a:b"`.
            txt = self._unquote(operand).lower()
            return txt in props.get('text', '')
        val = self._unquote(val.strip()).lower()
        if not val:
            return True
        if fld == 'level':
            expected = LEVEL_ALIASES.get(val, val)
            return props.get('level','info') == expected
        if fld == 'proc':
            return val in (props.get('proc') or '')
        if fld == 'pid':
            return val == (props.get('pid') or '')
        return val in (props.get('text') or '')  # text:

    def extract_props(self, block: str) -> dict:
        return self._extract_props_from_block(block)

    def _extract_props_from_block(self, block: str) -> dict:
        raw = block or ""
        level = get_log_level(raw)
        proc = ""
        pid = ""
        first_line = ""
        for ln in raw.splitlines():
            if ln.strip():
                first_line = ln.strip(); break
        if first_line:
            # Syslog iOS: «Oct 15 14:02:11 Имя-iPhone SpringBoard(FrontBoard)[58] <Notice>: …» —
            # процесс — слово прямо перед [pid], а не всё после времени (там
            # ещё имя устройства).
            header = re.match(r'^[A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+(?P<head>[^:<\n]+)', first_line)
            word_pid = re.search(r'(\S+)\[(\d{1,10})\]', header.group('head')) if header else None
            m = re.match(r'^[A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+(?P<proc>[^:\n<\[]+)', first_line)
            if word_pid:
                proc, pid = word_pid.group(1), word_pid.group(2)
            elif m:
                proc_candidate = m.group('proc').strip()
                pid_m = re.search(r'\[(\d{1,10})\]', first_line)
                pid = pid_m.group(1) if pid_m else ""
                proc = proc_candidate
            else:
                m2 = re.search(r'([^\s:\[]+)\[(\d{1,10})\]', first_line)
                if m2:
                    proc = m2.group(1); pid = m2.group(2)
        proc_norm = proc.strip().lower() if proc else ""
        text = raw.lower()
        return {"raw": raw, "level": level, "proc": proc_norm, "pid": pid, "text": text}
