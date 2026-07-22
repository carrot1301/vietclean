"""Compatibility API matching the ``dataclean`` import shown in the specification.

The implementation lives in :mod:`vietclean`; this module only re-exports its
documented public surface so existing examples can be used unchanged.
"""

from vietclean import *  # noqa: F403
from vietclean import __all__ as __all__
from vietclean import __version__ as __version__
