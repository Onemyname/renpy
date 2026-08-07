# packs/ — DLC-контент

Один пак = одно дерево, зеркалящее структуру `content/` (chapters/, characters/, loc/) + `manifest.yaml`
(`schema: pack_manifest@1`). Принадлежность паку определяется расположением — поля `pack:` в chapter.yaml
не существует. Механика загрузки и владения — раздел 6 ARCHITECTURE.md (G9/G10).

Заполняется в фазе 3.
