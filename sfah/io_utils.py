"""文本 I/O 与终端输出辅助工具。"""

from __future__ import annotations

import locale
import sys
from pathlib import Path
from typing import Iterable


def iter_text_encodings(extra: Iterable[str] | None = None) -> list[str]:
    """返回按优先级排序的文本编码列表。"""
    preferred = locale.getpreferredencoding(False) or "utf-8"
    candidates = ["utf-8", "utf-8-sig", preferred, "gbk", "cp936"]
    if extra:
        candidates.extend(extra)

    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def read_text_file(path: Path, extra_encodings: Iterable[str] | None = None) -> str:
    """按多种编码尝试读取文本文件。"""
    for encoding in iter_text_encodings(extra_encodings):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    return path.read_text(encoding="utf-8", errors="replace")


def write_text_file(path: Path, content: str, encoding: str | None = None) -> str:
    """写入文本文件，优先使用本地编码，不可编码时回退到 UTF-8。"""
    path.parent.mkdir(parents=True, exist_ok=True)

    if encoding:
        path.write_text(content, encoding=encoding)
        return encoding

    preferred = locale.getpreferredencoding(False) or "utf-8"
    ordered_candidates = [preferred, "utf-8", "utf-8-sig", "gbk", "cp936"]
    seen: list[str] = []
    for candidate in ordered_candidates:
        if candidate and candidate not in seen:
            seen.append(candidate)

    for candidate in seen:
        try:
            content.encode(candidate)
            path.write_text(content, encoding=candidate)
            return candidate
        except UnicodeEncodeError:
            continue

    path.write_text(content, encoding="utf-8")
    return "utf-8"


def console_supports_unicode() -> bool:
    """判断当前终端是否可稳定输出 Unicode。"""
    encoding = getattr(sys.stdout, "encoding", None) or locale.getpreferredencoding(False) or "utf-8"
    try:
        "🔴✅".encode(encoding)
        return True
    except UnicodeEncodeError:
        return False


def safe_console_text(text: str) -> str:
    """将文本转换为当前终端可输出的形式。"""
    encoding = getattr(sys.stdout, "encoding", None) or locale.getpreferredencoding(False) or "utf-8"
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding)
