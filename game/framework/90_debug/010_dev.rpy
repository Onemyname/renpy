# Dev-инструменты (раздел 1.2): вырезаются из release-профиля сборки (фаза 2).
# Чит-меню jump-to-scene генерируется из Scene Registry в фазе 2 (раздел 7).

# ВАЖНО: не писать `config.console = config.developer` в init-фазе — там developer
# ещё строка "auto" (truthy), и консоль включилась бы даже в release-сборке.
# Этот файл целиком вырезается из release-профиля (фаза 2), поэтому здесь честное True.
init python:
    config.console = True
