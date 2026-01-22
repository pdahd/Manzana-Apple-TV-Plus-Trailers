# utils/sanitize.py @ v0.2.0
#
# v0.2.0 changes:
# - Normalize FIRST (NFKC) then filter illegal characters.
#   This prevents cases where fullwidth punctuation (e.g. '：') becomes ASCII ':' after normalization.
# - Remove characters disallowed by actions/upload-artifact and Windows filesystems:
#   ", :, <, >, |, *, ?, CR/LF, plus path separators and NUL.
# - Remove all control characters (Unicode category "C*").

import unicodedata


# Characters that must not appear in filenames for cross-platform artifact compatibility.
_DISALLOWED = {
    "\\", "/", "\0",
    '"', ":", "<", ">", "|", "*", "?",
    "\r", "\n",
}

# Some Unicode variants are normalized by NFKC into the ASCII disallowed set above,
# but we still keep a defensive list for clarity/readability.
# (NFKC will typically convert these to ASCII equivalents.)
_UNICODE_PUNCT_VARIANTS = {
    "：",  # fullwidth colon
    "／",  # fullwidth slash
    "＼",  # fullwidth backslash
    "＂",  # fullwidth quotation mark
    "＜",  # fullwidth less-than
    "＞",  # fullwidth greater-than
    "｜",  # fullwidth vertical bar
    "＊",  # fullwidth asterisk
    "？",  # fullwidth question mark
}


def sanitize(f: str) -> str:
    if f is None:
        return ""

    # 1) Normalize first (compatibility normalization helps unify punctuation forms)
    f = unicodedata.normalize("NFKC", str(f))

    # 2) Remove explicitly disallowed characters (including variants)
    out_chars = []
    for c in f:
        if c in _DISALLOWED or c in _UNICODE_PUNCT_VARIANTS:
            continue
        # Remove all control characters (category "C*")
        if unicodedata.category(c).startswith("C"):
            continue
        out_chars.append(c)

    f = "".join(out_chars)

    # 3) Trim trailing dots/spaces (Windows limitation)
    f = f.rstrip(". ")

    # 4) Final trim
    return f.strip()
