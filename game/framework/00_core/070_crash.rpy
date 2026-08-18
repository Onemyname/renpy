# Продакшн-обработка краха (раздел 7, «последний эшелон»): breadcrumbs последних
# меток + crash-репорт в savedir. Первые эшелоны — shim-метки компилятора (G7)
# и сейв-миграции (G5); этот код работает, когда не спасло ничто.
#
# Разделение обязанностей: config.exception_handler здесь только ЛОГИРУЕТ, ПИШЕТ
# отчёт и возвращает False (=не обработано) — показ экрана остаётся движку, который
# берёт наш брендированный screen _exception (20_ui/screens/crash_screen.rpy)
# со штатными безопасными действиями rollback/ignore/reload.

init -950 python:
    import collections
    import io
    import os
    import time

    # Кольцевой буфер последних авторских меток — главный контекст диагностики
    # («где это случилось»), которого нет в голом трейсбеке.
    _vn_crash_breadcrumbs = collections.deque(maxlen=40)

    def _vn_crash_breadcrumb(name, abnormal):
        # Служебные метки движка (_*) шумят — в хлебные крошки не идут.
        if isinstance(name, str) and not name.startswith("_"):
            _vn_crash_breadcrumbs.append((time.strftime("%H:%M:%S"), name))

    config.label_callbacks.append(_vn_crash_breadcrumb)

    def _vn_crash_dir():
        base = config.savedir or config.basedir
        path = os.path.join(base, "crash")
        try:
            os.makedirs(path)
        except OSError:
            pass
        return path

    def vn_crash_write_report(te):
        """config.exception_handler (8.4+: один аргумент TracebackException).
        Единственный обработчик в проекте (см. 001_boot.rpy: второй там был мёртв).
        Любая ошибка внутри глотается: репортер не имеет права добить игру
        вторым исключением."""
        # Строка в log.txt пишется первой и отдельным try: разбор начинается с
        # `grep "\[vn\]" log.txt`, и факт падения не должен пропасть, если savedir
        # недоступен (нет прав, диск полон) и отчёт записать не удастся.
        try:
            # Берём последнюю непустую строку — это «Тип: сообщение», самое
            # информативное, что влезает в строку лога; первая строка te.simple —
            # лишь контекст движка («While running game code»).
            brief = getattr(te, "simple", None) or getattr(te, "full", None) or str(te)
            lines = [ln.strip() for ln in brief.splitlines() if ln.strip()]
            vn_log("unhandled exception: %s" % (lines[-1] if lines else "?"))
        except Exception:
            pass
        try:
            crash_dir = _vn_crash_dir()
            path = os.path.join(crash_dir,
                                "crash-%s.txt" % time.strftime("%Y%m%d-%H%M%S"))
            build = getattr(renpy.store, "vn_build", None)
            with io.open(path, "w", encoding="utf-8") as f:
                f.write("build: %s\n" % getattr(build, "build_id", "dev"))
                f.write("flavor: %s\n" % getattr(build, "flavor", "dev"))
                f.write("version: %s\n" % config.version)
                f.write("renpy: %s\n" % renpy.version())
                # Профиль платформы (ADR-0014): по нему видно, какой UI и какая
                # модель памяти были активны — мобильная и Deck-ветки иначе
                # неотличимы от десктопной по одному трейсбеку.
                try:
                    f.write("platform: %s\n" % renpy.store.vn_platform.describe())
                except Exception:
                    pass
                f.write("time: %s\n\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                f.write("Последние метки (breadcrumbs):\n")
                for ts, label in _vn_crash_breadcrumbs:
                    f.write("  %s  %s\n" % (ts, label))
                text = getattr(te, "full", None) or getattr(te, "simple", None) or te
                f.write("\n%s\n" % text)
            renpy.store._vn_last_crash_report = path
            # Дисциплина места: держим не больше 10 последних отчётов.
            reports = sorted(fn for fn in os.listdir(crash_dir)
                             if fn.startswith("crash-"))
            for old in reports[:-10]:
                try:
                    os.remove(os.path.join(crash_dir, old))
                except OSError:
                    pass
        except Exception:
            pass
        return False    # не handled: движок покажет наш screen _exception

    config.exception_handler = vn_crash_write_report
