#!/bin/sh
# Установка версионируемых git-hooks (ADR-0020). Идемпотентно: правки hook'ов
# делаются в ci/hooks/ и накатываются повторным запуском этого скрипта.
set -e
ROOT="$(git rev-parse --show-toplevel)"
cp "$ROOT/ci/hooks/pre-push" "$ROOT/.git/hooks/pre-push"
chmod +x "$ROOT/.git/hooks/pre-push"
echo "установлен: .git/hooks/pre-push (lint перед пушем + git-lfs)"
