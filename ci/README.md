# ci/

Скрипты проверок CI (фаза 1+: smoke затронутых глав под xvfb, bootstrap-джоба
«clone → запуск ≤ 5 минут», сейв-корпус `ci/fixtures/saves/`, weekly canary на свежем Ren'Py).

Конфиг пайплайна — корневой `.gitlab-ci.yml`; вся логика — в CLI `vn`,
поэтому перенос на GitHub Actions = те же четыре команды.
