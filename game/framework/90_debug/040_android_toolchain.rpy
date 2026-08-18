# Подготовка Android-сборки (RAPT) из командной строки — dev-зона, в дистрибутив
# не попадает (game/options.rpy: build.classify 90_debug -> None).
#
# Зачем это здесь, а не в tools/vn. Все три подготовительных шага RAPT живут
# внутри процесса движка: install_sdk импортирует renpy.pygame (нативный модуль),
# keys дописывает бэкап ключа рядом с сейвами через renpy.config, configure
# читает gradle.properties из каталога rapt. Системный python их не поднимет,
# поэтому запуск обязан идти через renpy.sh, то есть через зарегистрированную
# команду. Лаунчер SDK вызывает РОВНО эти же функции своими GUI-кнопками
# (launcher/game/android.rpy: label android_installsdk / android_keys /
# android_configure) — здесь тот же вызов без GUI.
#
# Сам RAPT (rapt/) в архив SDK не входит: его качают отдельным zip с renpy.org —
# этим занимается vn release android setup sdk --download-rapt.

init python:

    # Шаг -> функция RAPT. Порядок словаря = порядок прохождения: без Android SDK
    # нет keytool для ключей, без ключей нечего подписывать.
    def _vn_android_step_sdk(rapt, iface):
        rapt.install_sdk.install_sdk(iface)

    def _vn_android_step_keys(rapt, iface):
        rapt.keys.generate_keys(iface, config.basedir)

    def _vn_android_step_config(rapt, iface):
        # Имя и версию приложения даёт сам проект (config.name/config.version):
        # спрашивать их у человека, когда они уже объявлены в дереве, — способ
        # разойтись с ними. Лаунчер делает то же самое через project.dump.
        rapt.configure.configure(iface, config.basedir,
                                 default_name=config.name,
                                 default_version=config.version)

    VN_ANDROID_STEPS = {
        "sdk": _vn_android_step_sdk,
        "keys": _vn_android_step_keys,
        "config": _vn_android_step_config,
    }

    def _vn_android_toolchain_command():
        import os
        import sys

        ap = renpy.arguments.ArgumentParser()
        ap.add_argument("rapt_path", help="Каталог rapt/ внутри SDK")
        ap.add_argument("step", choices=sorted(VN_ANDROID_STEPS),
                        help="Подготовительный шаг RAPT")
        args = ap.parse_args()

        rapt_path = os.path.abspath(args.rapt_path)
        buildlib = os.path.join(rapt_path, "buildlib")
        if not os.path.isdir(buildlib):
            print("нет %s — RAPT не распакован" % buildlib)
            return False

        # rapt рассчитывает, что процесс работает ИЗ своего каталога: пути к
        # buildlib/CheckJDK.java, android-sdk/ и project/ он строит от cwd.
        os.chdir(rapt_path)
        if buildlib not in sys.path:
            sys.path.insert(0, buildlib)

        import rapt
        import rapt.build
        import rapt.configure
        import rapt.install_sdk
        import rapt.interface
        import rapt.keys

        # Дефект RAPT 8.5.3: Interface.choice печатает варианты как
        # write(текст, Style.BRIGHT), но `Style` в rapt/interface.py не
        # импортирован — консольный Interface падает на NameError. Лаунчер этого
        # не видит: его MobileInterface перекрывает write и до Style не доходит.
        # Подставляем отсутствующее имя (яркость — косметика), не трогая логику,
        # и только если RAPT его сам не завёл: в новой версии импорт может
        # появиться, и тогда наш стаб не должен его затирать.
        if not hasattr(rapt.interface, "Style"):
            class _NoStyle(object):
                BRIGHT = ""
            rapt.interface.Style = _NoStyle

        try:
            VN_ANDROID_STEPS[args.step](rapt, rapt.interface.Interface())
        except SystemExit:
            raise
        except Exception as e:
            # Ненулевой код выхода обязателен: по нему vn отличает провал шага от
            # успеха (иначе CLI отрапортует OK на упавшей подготовке).
            raise SystemExit("шаг %s не удался: %r" % (args.step, e))
        return False

    renpy.arguments.register_command("vn_android_toolchain",
                                     _vn_android_toolchain_command)
