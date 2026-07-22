"""Stable exception hierarchy used by the library and CLI exit-code mapping."""


class DataCleanError(Exception):
    """Public root exception for all expected framework failures."""

    code = "VC-000"


class VietCleanError(DataCleanError):
    """Base class for expected VietClean failures."""

    code = "VC-000"


class ConfigurationError(VietCleanError, ValueError):
    code = "VC-CONFIG-001"


class InputFileError(VietCleanError, OSError):
    code = "VC-INPUT-001"


class UnsupportedFormatError(VietCleanError, ValueError):
    code = "VC-FORMAT-001"


class UnsafeInputError(VietCleanError, ValueError):
    code = "VC-SAFE-001"


class EncodingDetectionError(InputFileError):
    code = "VC-ENCODING-001"


class SchemaValidationError(VietCleanError, ValueError):
    code = "VC-VALIDATE-001"


class ExportError(VietCleanError, OSError):
    code = "VC-EXPORT-001"


class ResourceLimitError(UnsafeInputError):
    code = "VC-LIMIT-001"


class UnsafeQueryError(UnsafeInputError):
    code = "VC-SQL-001"


__all__ = [
    "ConfigurationError",
    "DataCleanError",
    "EncodingDetectionError",
    "ExportError",
    "InputFileError",
    "ResourceLimitError",
    "SchemaValidationError",
    "UnsafeInputError",
    "UnsafeQueryError",
    "UnsupportedFormatError",
    "VietCleanError",
]
