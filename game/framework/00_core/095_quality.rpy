# Потолок качества текстур: ограничение автоподбора @N СВЕРХУ по выбору игрока.
#
# Автоподбор оверсэмпла (ADR-0012) выбирает вариант по ФИЗИЧЕСКОМУ экрану и не
# знает про GPU: 4K-монитор со слабой видеокартой получает @2-текстуры, которые
# железо не тянет. Потолок сборки задаёт render.gen.rpy
# (vn_build_max_oversampling из project.yaml: render.max_oversampling);
# игрок может только ОПУСТИТЬ его — поднять выше отгруженных вариантов нельзя.
#
# Оба API документированы (config.automatic_oversampling, renpy.free_memory) —
# engine_compat не требуется.

init 999 python:
    # Сохранённый выбор применяется до первой интеракции: config читается при
    # загрузке образа, к этому моменту ещё ничего не декодировано.
    if persistent.vn_quality_cap:
        # getattr, а не голое имя: потолок сборки живёт в генерате (render.gen.rpy),
        # а persistent глобален и переживает переклон репозитория — на свежем
        # чекауте без vn content compile голое имя дало бы NameError на init,
        # то есть игра не запускалась бы вообще (принцип «пустой проект стартует
        # и честно говорит, что контента нет», 010_registry.rpy). Дефолт тот же,
        # что у set_quality_cap ниже.
        config.automatic_oversampling = min(
            int(persistent.vn_quality_cap),
            getattr(store, "vn_build_max_oversampling", 4))


init -998 python in vn:

    def quality_cap():
        """Текущий потолок игрока: None = авто (потолок сборки)."""
        return renpy.store.persistent.vn_quality_cap

    def set_quality_cap(cap):
        """Сменить потолок на лету: выставить config и освободить кэш
        декодированных образов — уже показанные текстуры перезагрузятся в новом
        качестве при следующем показе, перезапуск игры не нужен."""
        build_max = getattr(renpy.store, "vn_build_max_oversampling", 4)
        renpy.store.persistent.vn_quality_cap = cap
        renpy.store.config.automatic_oversampling = min(cap or build_max, build_max)
        renpy.free_memory()
        renpy.restart_interaction()
