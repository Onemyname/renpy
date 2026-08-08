# game/fonts/ — шрифты UI (единственный разрешённый бинарь в game/)

Положить сюда (имена — ровно как в gui.rpy):

| Файл | Откуда | Лицензия |
|---|---|---|
| Literata-Regular.ttf | github.com/googlefonts/literata (fonts/ttf) | OFL 1.1 |
| Inter-Regular.ttf | github.com/rsms/inter (releases) | OFL 1.1 |
| Inter-SemiBold.ttf | github.com/rsms/inter (releases) | OFL 1.1 |

Рядом — тексты лицензий: `OFL-Literata.txt`, `OFL-Inter.txt`.

Оба семейства покрывают кириллицу полностью (исходный язык — ru) и латиницу
расширенную (en/de). CJK-языки приходят со своим шрифтом через манифест
language.json пакета перевода (language_picker уже делает fallback).

Не забыть: зарегистрировать в content/licenses.yaml (schema licenses@1).

Использование ТОЛЬКО через gui.text_font / gui.name_text_font /
gui.interface_text_font / gui.interface_semibold_font — теги {font=...}
в текстах и хардкод путей в стилях запрещены (языковые пакеты
переопределяют шрифты через gui.* и манифесты).
