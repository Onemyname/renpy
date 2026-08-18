# Реестры (раздел 1.8, слой 0). Данные реестров — генерат (init -100 и 500),
# здесь — только доступ к ним. Framework никогда не ссылается на конкретные главы.

init -999 python in vn_registry:
    from store import renpy

    def chapters():
        """Список глав из Chapter Registry (define VN_CHAPTERS, эмитится компилятором).
        Пустой проект -> пустой список: игра запускается и честно говорит, что контента нет."""
        return list(getattr(renpy.store, "VN_CHAPTERS", ()))

    def chapter_title(chapter_id):
        """Локализованный заголовок главы по её id (для save_name: список сейвов и
        фазы Steam Timeline). Неизвестная глава -> её id: в заголовке слота лучше
        служебная строка, чем пустое место."""
        for row in chapters():
            if row["id"] == chapter_id:
                return renpy.store.vn_loc.t(row["title_key"])
        return chapter_id

    def menus():
        """Реестр choice-id (define VN_MENUS, generated/registry/menus.gen.rpy)."""
        return getattr(renpy.store, "VN_MENUS", {})

    def scene_label(full_id):
        """Метка-обвязка сцены = её полный id (G7)."""
        return full_id
