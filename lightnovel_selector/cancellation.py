from __future__ import annotations


class OperationCancelled(RuntimeError):
    """表示用户主动取消扫描，供各层统一传播。"""
