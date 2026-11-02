"""Lightweight error detection used by the debugger and the community bots."""
import re
from dataclasses import dataclass


@dataclass
class DetectedError:
    language: str
    error_type: str
    hint: str


_PATTERNS = [
    (r"\b(IndexError)\b", "Python", "You used an index that does not exist. Check `len(...)` before indexing."),
    (r"\b(KeyError)\b", "Python", "The dictionary has no such key. Use `dict.get(key)` or check `key in dict`."),
    (r"\b(TypeError)\b.*(NoneType|unsupported operand|not callable)", "Python",
     "An operation was applied to the wrong type, often `None`. Print the variable's value and type."),
    (r"\b(NameError)\b", "Python", "A variable or function is used before it is defined, or is misspelled."),
    (r"\b(ModuleNotFoundError|ImportError)\b", "Python", "The package is not installed. Run `pip install <package>`."),
    (r"\b(ZeroDivisionError)\b", "Python", "You divided by zero. Guard the divisor with an `if`."),
    (r"\b(AttributeError)\b", "Python", "The object has no such attribute. Check its type and spelling."),
    (r"\b(IndentationError|SyntaxError)\b", "Python", "Check brackets, colons and indentation near the reported line."),
    (r"Cannot read propert(?:y|ies) of (undefined|null)", "JavaScript",
     "You accessed a property on `undefined`/`null`. Use optional chaining (`obj?.prop`) or check the value first."),
    (r"\b(ReferenceError)\b", "JavaScript", "A variable is used before declaration or is out of scope."),
    (r"(is not a function)", "JavaScript", "You called something that is not a function. Check the import and its type."),
    (r"\b(NullPointerException)\b", "Java", "A reference is `null` when used. Add a null check or initialise it."),
    (r"(cannot find symbol)", "Java", "A name is not declared or an import is missing."),
    (r"\b(ArrayIndexOutOfBoundsException)\b", "Java", "The array index is outside `0..length-1`."),
    (r"(syntax error at or near|no such table|no such column|Unknown column)", "SQL",
     "Check keywords, commas, and that the table/column names exist."),
    (r"Traceback \(most recent call last\)", "Python", "Read the last line of the traceback first: it names the error."),
    (r"\b(\w+Error|\w+Exception):", "Unknown", "Read the message after the colon and find the line it points to."),
]


def detect_error(text: str) -> DetectedError | None:
    for pattern, language, hint in _PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL if "NoneType" in pattern else re.IGNORECASE)
        if match:
            return DetectedError(language, match.group(1) if match.groups() else "Error", hint)
    return None
