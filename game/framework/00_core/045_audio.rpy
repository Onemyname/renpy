# Аудио-рантайм (C18, §4.9): канал эмбиенса, дакинг под голос, резолвер озвучки.
#
# Каналов ровно столько, сколько есть контента: bgm — штатный music, amb — свой
# зацикленный канал (раньше amb играл на music и ВЫТЕСНЯЛ музыку), sfx — штатный
# sound, голос — штатный voice. foley/voicefx из референсов конкурентов не
# заводятся, пока для них нет ни контента, ни схемы — пустой канал это мёртвый код.

init -900 python:
    # Эмбиенс локации: зацикленный, на микшере music — громкость игрок регулирует
    # существующим слайдером музыки (отдельный слайдер появится вместе с настройками
    # микшера, если контент покажет, что он нужен). tight: бесшовный кроссфейд
    # хвоста при смене файла на канале.
    renpy.music.register_channel("ambient", mixer="music", loop=True, tight=True)

    # Дакинг: пока звучит канал voice, остальные каналы приглушаются ШТАТНЫМ
    # механизмом движка — своей математики громкостей не вводим (документировано:
    # config.emphasize_audio_*). Без озвучки конфиг безвреден: канал voice молчит.
    config.emphasize_audio_channels = ["voice"]
    config.emphasize_audio_volume = 0.6
    config.emphasize_audio_time = 0.5


# store vn создан на init -999 (030_flow.rpy); здесь только дополняем фасад.
init -998 python in vn:

    def voice_path(line_id):
        """Файл озвучки реплики для текущего языка с деградацией до оригинала (§4.9/C5).

        Компилятор эмитит `voice vn.voice_path("<line_id>")` перед каждой репликой,
        покрытой хотя бы одним voice-манифестом. Язык озвучки следует за языком
        текста; недостающая локаль войса играет оригиналом. Возвращает "" (falsy),
        когда файла нет ни в одном языке — например, voice-пак не установлен:
        voice-оператор движка с falsy-именем — no-op (контракт-тест engine_compat).

        Путь шардирован по главе (line_id несёт её префикс): тысячи файлов в одном
        каталоге — боль и для ФС, и для Steam-депотов voice-паков."""
        langs = [renpy.store.vn_lang.current()]
        src = (getattr(renpy.store, "VN_SOURCE_LANG", None) or {}).get("code")
        if src and src not in langs:
            langs.append(src)
        for lang in langs:
            fn = "assets/voice/%s/%s/%s.opus" % (lang, line_id[:4], line_id)
            if renpy.loadable(fn):
                return fn
        return ""
