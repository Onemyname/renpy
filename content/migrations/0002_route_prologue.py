"""Миграция схемы 1 -> 2: значение route 'common' переименовано в 'prologue'.

Контракт (G5): migrate(state: dict) -> dict над плоским снапшотом stores;
только простые типы; исполняется в игре (after_load) и внешним тулингом одинаково.
"""


def migrate(state):
    if state.get("g.route") == "common":
        state["g.route"] = "prologue"
    return state
