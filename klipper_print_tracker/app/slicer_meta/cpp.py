"""Just enough C++ reading for the slicer sources: comments, strings and method bodies."""
import re

_LITERAL = r'(?:u8)?"(?:\\.|[^"\\\n])*"'
LITERALS = rf"(?:{_LITERAL}\s*)+"
_TOKENS = re.compile(rf"({_LITERAL})|//[^\n]*|/\*.*?\*/", re.DOTALL)
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "'": "'"}


def strip_comments(source: str) -> str:
    return _TOKENS.sub(lambda m: m.group(1) or " ", source)


def unescape(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(0)), text)


def strings(literals: str) -> str:
    """The value of adjacent string literals."""
    return "".join(unescape(m.group(1)) for m in re.finditer(r'"((?:\\.|[^"\\\n])*)"', literals))


def method_body(source: str, signature: str) -> str | None:
    """Text between the braces of a method, or None when it doesn't exist."""
    found = re.search(re.escape(signature) + r"\s*\([^)]*\)\s*\{", source)
    if not found:
        return None
    depth, pos = 1, found.end()
    start = pos
    token = re.compile(rf"{_LITERAL}|'(?:\\.|[^'\\])'|[{{}}]")
    while depth:
        match = token.search(source, pos)
        if not match:
            return None
        pos = match.end()
        if match.group() == "{":
            depth += 1
        elif match.group() == "}":
            depth -= 1
    return source[start:pos - 1]
