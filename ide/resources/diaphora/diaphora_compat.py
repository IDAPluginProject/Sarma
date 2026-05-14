"""
Small compatibility helpers for Diaphora across IDA/Python UI versions.
"""

from __future__ import annotations


def import_qtwidgets():
  """
  Return the QtWidgets module used by the current IDA build.
  """
  try:
    from PySide6 import QtWidgets
    return QtWidgets
  except ImportError:
    from PyQt5 import QtWidgets
    return QtWidgets


def refresh_builtin_widgets(mask=None):
  """
  Mark IDA builtin widgets as dirty on old and new IDA UI APIs.
  """
  import idaapi

  try:
    import ida_kernwin
  except ImportError:
    ida_kernwin = idaapi

  if hasattr(ida_kernwin, "mark_builtin_widgets"):
    if mask is None:
      mask = getattr(ida_kernwin, "IWID_ALL", (1 << 128) - 1)
    ida_kernwin.mark_builtin_widgets(mask, True)
    return

  if hasattr(idaapi, "request_refresh"):
    if mask is None:
      mask = 0xFFFFFFFF
    idaapi.request_refresh(mask)
