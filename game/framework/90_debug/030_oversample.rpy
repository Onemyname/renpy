# Проверка оверсэмпла НАСТОЯЩИМ движком (ADR-0012).
#
# Весь смысл варианта `<name>@2` в том, что Ren'Py подставит его сам на экране
# крупнее виртуального. Если бы автоподбор не срабатывал (не тот префикс загрузчика,
# не та форма имени, выключенный config.automatic_oversampling), мы бы молча
# отгружали 4K-ассеты, которых никто никогда не увидит, — и ни один наш тест на
# Python этого не поймал бы: решение принимает движок, а не конвейер.
#
# Поэтому здесь дёргается ИМЕННО движковый Image.get_oversampled_image() с
# подставленным draw_per_virt (реального окна в этом режиме нет), и результат
# сверяется с ожиданием. Команда живёт в 90_debug — в релизный билд не попадает
# (options.rpy: build.classify("game/framework/90_debug/**", None)).
#
#   renpy.exe <project> vn_oversample [--scale 2]

init python:
    def _vn_oversample_command():
        import os
        import renpy.display.im as im

        ap = renpy.arguments.ArgumentParser()
        ap.add_argument("--scale", type=float, default=2.0,
                        help="Во сколько раз физический экран крупнее виртуального.")
        args = ap.parse_args()

        class _Draw(object):
            draw_per_virt = args.scale

        saved = renpy.display.draw
        renpy.display.draw = _Draw()
        try:
            assets = os.path.join(renpy.config.gamedir, "assets")
            checked = upgraded = 0
            failures = []
            for dirpath, _dirs, files in os.walk(assets):
                for name in sorted(files):
                    stem, ext = os.path.splitext(name)
                    if ext not in (".webp", ".png", ".jpg"):
                        continue
                    if "@" in stem or stem.endswith(".thumb"):
                        continue            # варианты и миниатюры — не точки входа
                    rel = os.path.relpath(os.path.join(dirpath, name),
                                          renpy.config.gamedir).replace("\\", "/")
                    checked += 1
                    resolved = im.Image(rel).get_oversampled_image().filename
                    sibling = "%s@%d%s" % (rel[:-len(ext)], int(args.scale), ext)
                    if renpy.loader.loadable(sibling, directory="images"):
                        if resolved != sibling:
                            failures.append("%s: вариант %s есть, но движок остался "
                                            "на %s" % (rel, sibling, resolved))
                        else:
                            upgraded += 1
                    elif resolved != rel:
                        failures.append("%s: варианта нет, а движок ушёл на %s"
                                        % (rel, resolved))
        finally:
            renpy.display.draw = saved

        print("oversample @%g: проверено %d, поднято до варианта %d"
              % (args.scale, checked, upgraded))
        for f in failures:
            print("FAIL %s" % f)
        if failures:
            return False
        if not upgraded:
            print("FAIL ни один ассет не получил крупный вариант — "
                  "автоподбор не работает или варианты не собраны")
            return False
        print("oversample: OK")
        return False        # False = не запускать игру после команды

    renpy.arguments.register_command("vn_oversample", _vn_oversample_command)
