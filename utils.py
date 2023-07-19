"""General utilities."""

import os
import string


def nonascii(chars: str) -> str:
    """Get the first non-ASCII character from the given characters, if any."""
    for char in chars:
        if char not in string.printable:
            return char
    return ''


def splitext(path: str) -> tuple[str, str]:
    """Split the pathname `path` into a pair."""
    tail = os.path.split(path)[1]

    extension = ''.join(t[1:]) if (t := tail.rpartition('.'))[1] else t[1]

    filename = path.removesuffix(extension)

    return filename, extension
