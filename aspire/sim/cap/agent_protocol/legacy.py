"""Explicit legacy decision adapter; dynamic-v2 never calls this module."""


def parse_legacy_decision(content: str) -> tuple[str, str | None]:
    if "REGENERATE" in content:
        return "regenerate", content.split("REGENERATE", 1)[1].strip()
    if content.strip() == "FINISH":
        return "finish", None
    return "continue", content
