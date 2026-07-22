"""Conservative allowlist for read-only SQL imports."""

from __future__ import annotations

import re

from ..exceptions import UnsafeQueryError


_WRITE_KEYWORDS = re.compile(
    r"\b(?:alter|attach|call|copy|create|delete|detach|drop|execute|grant|insert|"
    r"into|merge|pragma|reindex|replace|revoke|truncate|update|vacuum)\b",
    flags=re.IGNORECASE,
)


def validate_read_query(query: str) -> str:
    """Validate and return one SELECT/CTE statement.

    This is intentionally stricter than a SQL parser: comments and embedded
    semicolons are rejected, including when they appear inside a string. Users
    can express values through parameterized query arguments instead.
    """

    if not isinstance(query, str) or not query.strip():
        raise UnsafeQueryError("[VC-SQL-001] Query import không được để trống.")
    if "\x00" in query:
        raise UnsafeQueryError("[VC-SQL-001] Query chứa null byte.")
    statement = query.strip()
    if statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if ";" in statement:
        raise UnsafeQueryError("[VC-SQL-001] Chỉ cho phép một SQL statement.")
    if "--" in statement or "/*" in statement or "*/" in statement:
        raise UnsafeQueryError("[VC-SQL-001] Comment SQL không được phép trong read-only mode.")
    if not re.match(r"^(?:select|with)\b", statement, flags=re.IGNORECASE):
        raise UnsafeQueryError("[VC-SQL-001] Import database chỉ cho phép SELECT hoặc WITH.")
    match = _WRITE_KEYWORDS.search(statement)
    if match:
        raise UnsafeQueryError(
            f"[VC-SQL-001] Từ khóa '{match.group(0).upper()}' không được phép trong read-only mode."
        )
    return statement
