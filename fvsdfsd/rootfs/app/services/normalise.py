from __future__ import annotations

import re


def tidy(s: str | None) -> str:
    value = (s or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\(.*?remaster.*?\)", "", value)
    value = re.sub(r"\(.*?radio edit.*?\)", "", value)
    value = re.sub(r"\(.*?version.*?\)", "", value)
    value = re.sub(r"\[.*?remaster.*?\]", "", value)
    value = re.sub(r"feat\.? .*", "", value)
    value = re.sub(r"ft\.? .*", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -")


def make_search_query(title: str, artist: str) -> str:
    return f"{tidy(title)} {tidy(artist)}".strip()
