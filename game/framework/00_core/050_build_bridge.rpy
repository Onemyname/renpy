# Build-bridge (G24): анализ авторских scene.rpy ПАРСЕРОМ САМОГО Ren'Py.
# Компилятор (tools/vn) вызывает:
#   renpy.exe <root> vn_analyze <out.json> --files-from <список>
# Список файлом, а не аргументами: на десятках тысяч сцен argv не влезает в ARG_MAX
# (подробности и цифры — в tools/vn/src/vn/content/analyze.py). Прямые аргументы
# мост понимает по-прежнему — им его зовут руками при отладке одной сцены.
# Команда исполняется после init, до главного цикла; return False = не запускать игру.
# Регексы по .rpy запрещены архитектурой — это единственный легальный способ разбора.

init python:

    import ast as _vn_ast
    import builtins as _vn_builtins
    import re as _vn_re

    # Имена list/dict/set в сторе — Revertable-аналоги (SDK renpy/minstore.py:41-53),
    # а AST приходит из renpy.parser (обычный python-модуль) обычными контейнерами.
    # Проверять их тип по подменённым именам значит не распознать НИ ОДИН из них.
    _VN_LIST = _vn_builtins.list
    _VN_DICT = _vn_builtins.dict

    # Управляемые named stores (зеркало vars@1.store): только их атрибуты едут в
    # сейв и миграции. Обращение к атрибуту вне реестра — молчаливый фантом (G5).
    _VN_STORE_RE = _vn_re.compile(r"^(g|ch\d{2}|mech_[a-z0-9_]+|dlc_[a-z0-9_]+|persistent)$")

    def _vn_new_entry():
        """Пустой аккумулятор анализа файла. Той же формой разбирается ОТДЕЛЬНО
        каждый пункт меню (см. Menu ниже): знать, какой exit возвращает пункт и
        что он пишет, иначе неоткуда — в общем списке эта связь теряется."""
        return {
            "labels": [], "jumps": [], "calls": [], "returns": [],
            "menus": [], "says": 0, "say_list": [], "menu_markers": [],
            "var_reads": [], "var_writes": [], "assigns": [], "errors": [],
            "image_refs": [], "audio_refs": [], "branch_assigns": [],
            "beats": [],
        }

    # Ключи, где дубликаты недопустимы: их накапливают проверкой «не было ли уже».
    _VN_UNIQUE_KEYS = ("var_reads", "var_writes", "beats")

    def _vn_merge_entry(dst, src):
        """Слить под-аккумулятор пункта меню в общий: формы одинаковы, поэтому
        списки продолжаются, счётчик реплик суммируется, а уникальные ключи
        сохраняют семантику множества."""
        for key, value in src.items():
            if key == "says":
                dst[key] += value
            elif key in _VN_UNIQUE_KEYS:
                for item in value:
                    if item not in dst[key]:
                        dst[key].append(item)
            else:
                dst[key].extend(value)

    def _vn_collect_vars(source, mode, entry):
        """Извлечь чтения/записи атрибутов управляемых stores из python-фрагмента
        или выражения-условия. Классификация по ast-контексту: Store=запись,
        Load=чтение. Непарсящийся фрагмент молча пропускается (не валим анализ).

        Побочно собирает `assigns` — присваивания ЛИТЕРАЛОВ (`$ ch01.flag = True`):
        без значения запись переменной ничего не говорит о том, какое состояние
        ветка создаёт, а на этом стоят и достижимость, и прекондиции реплея."""
        if not source:
            return
        try:
            tree = _vn_ast.parse(source, mode=mode)
        except (SyntaxError, ValueError):
            return
        for node in _vn_ast.walk(tree):
            if not isinstance(node, _vn_ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, _vn_ast.Attribute):
                continue
            base = target.value
            if not isinstance(base, _vn_ast.Name) or not _VN_STORE_RE.match(base.id):
                continue
            try:
                literal = _vn_ast.literal_eval(node.value)
            except (ValueError, SyntaxError, TypeError):
                continue        # выражение, а не литерал: значение неизвестно
            if isinstance(literal, (str, int, float, bool)) or literal is None:
                entry["assigns"].append({
                    "var": "%s.%s" % (base.id, target.attr), "value": literal,
                })
        # Именованные биты: `$ vn.beat("roof_alone")`. Без этого списка ЯКОРЬ
        # `beat` в галерее и достижениях не проверялся вообще ничем — опечатка в
        # имени давала элемент, который не откроется никогда, при зелёной сборке.
        # `vn` не подходит под _VN_STORE_RE (это фасад, а не управляемый store),
        # поэтому сбор отдельным проходом по вызовам. Разбирается СТРОКА, которую
        # отдал парсер Ren'Py (node.code.source), питоновским ast — второго
        # разборщика .rpy здесь не появляется (G24).
        for node in _vn_ast.walk(tree):
            if not isinstance(node, _vn_ast.Call):
                continue
            func = node.func
            if not isinstance(func, _vn_ast.Attribute) or func.attr != "beat":
                continue
            if not isinstance(func.value, _vn_ast.Name) or func.value.id != "vn":
                continue
            if not node.args:
                continue
            try:
                name = _vn_ast.literal_eval(node.args[0])
            except (ValueError, SyntaxError, TypeError):
                continue        # выражение, а не литерал: имя неизвестно
            if isinstance(name, str) and name not in entry["beats"]:
                entry["beats"].append(name)
        for node in _vn_ast.walk(tree):
            if not isinstance(node, _vn_ast.Attribute):
                continue
            base = node.value
            if not isinstance(base, _vn_ast.Name) or not _VN_STORE_RE.match(base.id):
                continue
            ref = "%s.%s" % (base.id, node.attr)
            if isinstance(node.ctx, _vn_ast.Store):
                if ref not in entry["var_writes"]:
                    entry["var_writes"].append(ref)
            elif isinstance(node.ctx, _vn_ast.Load):
                if ref not in entry["var_reads"]:
                    entry["var_reads"].append(ref)

    def _vn_imspec(imspec):
        """imspec -> (кортеж имени образа, выражение-строка или None).
        Форм у кортежа несколько (renpy/ast.py: ImspecType); отличаются они тем,
        что во «длинных» формах во втором поле лежит строка-выражение
        (`show expression ...`), а в короткой — список at-трансформов."""
        if not imspec:
            return None, None
        name = imspec[0]
        expr = imspec[1] if len(imspec) > 1 and isinstance(imspec[1], str) else None
        return (tuple(name) if name else None), expr

    def _vn_record_image(entry, kind, node, line):
        name, expr = _vn_imspec(getattr(node, "imspec", None))
        if name is None and expr is None:
            return              # `scene` без образа — просто очистка слоя
        entry["image_refs"].append({
            "line": line, "kind": kind,
            "name": list(name) if name else None,
            "expression": bool(expr),
        })

    def _vn_terminates(block):
        """Завершается ли блок гарантированно — Return или Jump по ВСЕМ путям.

        Зачем это компилятору: авторский .rpy вклеивается в генерат целиком, а
        Ren'Py сшивает операторы файла подряд (renpy/script.py: chain_block).
        Значит блок метки, из которого можно ВЫПАСТЬ, исполняет следующий
        оператор файла — соседнюю авторскую метку. Игрок, выбравший «остаться»,
        оказывается в ветке «ушёл», и заметить это нечем: G7-страж стоит после
        call ...__body, а соседняя ветка делает свой return, так что глубина
        стека корректна и обвязка исполняет ЧУЖОЙ exit как свой.

        Разбор рекурсивный: у if обязаны завершаться все ветки И присутствовать
        else (иначе есть путь мимо), у menu — все пункты. Всё прочее в хвосте
        (say, show, python) завершением не является."""
        if not block:
            return False
        last = block[-1]
        cls = type(last).__name__
        if cls in ("Return", "Jump"):
            return True
        if cls == "If":
            entries = list(getattr(last, "entries", []))
            if not entries:
                return False
            has_else = str(entries[-1][0]) in ("True", "None")
            return has_else and all(_vn_terminates(b) for _cond, b in entries)
        if cls == "Menu":
            items = [it for it in getattr(last, "items", []) if it[2] is not None]
            return bool(items) and all(_vn_terminates(it[2]) for it in items)
        if cls == "While":
            return False        # цикл может не выполниться ни разу
        return False

    def _vn_walk_ast(nodes, entry):
        for node in nodes:
            cls = type(node).__name__
            line = getattr(node, "linenumber", 0)
            if cls in ("Show", "Scene", "Hide"):
                _vn_record_image(entry, cls.lower(), node, line)
            elif cls == "UserStatement":
                # play/queue/stop — зарегистрированные стейтменты; их разобранная
                # форма лежит в node.parsed как (имя, payload). Имя аудио приходит
                # ИСХОДНЫМ ВЫРАЖЕНИЕМ (l.simple_expression), т.е. `calm_theme`
                # для `play music calm_theme` (renpy/common/000statements.rpy).
                try:
                    stmt = node.get_name()
                except Exception:
                    stmt = ""
                parsed = getattr(node, "parsed", None)
                payload = parsed[1] if isinstance(parsed, tuple) and len(parsed) == 2 else None
                if isinstance(payload, _VN_DICT) and stmt.split(" ")[0] in ("play", "queue"):
                    entry["audio_refs"].append({
                        "line": line, "stmt": stmt,
                        "file": payload.get("file"),
                        "channel": payload.get("channel"),
                    })
            elif cls == "Label":
                entry["labels"].append({"name": node.name, "line": line,
                                        "terminal": _vn_terminates(node.block)})
                _vn_walk_ast(node.block, entry)
            elif cls == "Jump":
                entry["jumps"].append({
                    "target": node.target, "line": line,
                    "expression": bool(node.expression),
                })
            elif cls == "Call":
                entry["calls"].append({
                    "target": node.label, "line": line,
                    "expression": bool(node.expression),
                })
            elif cls == "Return":
                expr = node.expression
                entry["returns"].append({
                    "expr": expr if isinstance(expr, str) else None, "line": line,
                })
            elif cls == "Say":
                entry["says"] += 1
                entry["say_list"].append({
                    "line": line,
                    "who": node.who if isinstance(node.who, str) else None,
                    "what": node.what,
                    "id": getattr(node, "identifier", None),
                    # interact=False бывает ровно у реплики-ЗАГОЛОВКА меню:
                    # parse_menu зовёт finish_say(..., interact=False) и кладёт
                    # получившийся Say ОТДЕЛЬНЫМ узлом ПЕРЕД Menu (parser.py),
                    # с номером строки внутри блока menu:. По соседству Say с
                    # Menu их не различить — обычная реплика перед меню выглядит
                    # так же, — а по этому флагу различить можно.
                    "interact": bool(getattr(node, "interact", True)),
                })
            elif cls == "Python":
                src = getattr(getattr(node, "code", None), "source", "") or ""
                if src.strip().startswith("vn_menu"):
                    entry["menu_markers"].append({"line": line, "source": src.strip()})
                _vn_collect_vars(src, "exec", entry)   # $ ch01.x = True / python:-блоки
            elif cls == "Menu":
                captions = []
                conditions = []
                choices = []
                for idx, item in enumerate(node.items):
                    caption, condition, block = item[0], item[1], item[2]
                    captions.append(caption)
                    conditions.append(str(condition))
                    _vn_collect_vars(str(condition), "eval", entry)
                    # Блок пункта разбирается в СВОЙ аккумулятор: только так видно,
                    # какой exit возвращает именно этот пункт и что он пишет.
                    # Результаты затем сливаются в общий, поэтому остальные
                    # потребители анализа (loc, ссылки, переменные) не замечают
                    # разницы.
                    sub = _vn_new_entry()
                    if block:
                        _vn_walk_ast(block, sub)
                    choices.append({
                        "idx": idx,
                        "caption": caption,
                        "condition": str(condition),
                        "returns": [r["expr"] for r in sub["returns"]
                                    if r["expr"] is not None],
                        "jumps": [j["target"] for j in sub["jumps"]
                                  if not j["expression"]],
                        "assigns": list(sub["assigns"]),
                    })
                    _vn_merge_entry(entry, sub)
                entry["menus"].append({"line": line, "items": captions,
                                       "conditions": conditions,
                                       "choices": choices})
            elif cls == "If":
                # Каждая ветвь — в СВОЙ аккумулятор, тем же приёмом, что пункты
                # меню выше. Раньше все ветви писали в один плоский
                # entry["assigns"], без пометки «условное», и потребитель
                # (flow._apply) исполнял остаток как прямую последовательность:
                # после `if x: v = A` / `else: v = B` мир единственный и в нём
                # v == B, а у `if` без `else` бонусная ветка применялась
                # БЕЗУСЛОВНО. Следствие — ложное «сцена недостижима» за условием:
                # узел навсегда «???», в модалке карты нет ни одной кнопки
                # «Переиграть» (они строятся по пустым preconds), и гайд к цели не
                # ведёт. После сплющивания эта информация утеряна безвозвратно,
                # поэтому разводить ветви обязан именно мост.
                #
                # В общий assigns ветви НЕ вливаются: там лежат только безусловные
                # присваивания тела. Всё остальное (var_reads/var_writes, реплики,
                # returns, вложенные меню) сливается как обычно — эти списки
                # обязаны быть полными, иначе сломаются проверки деклараций и loc.
                for _condition, block in node.entries:
                    _vn_collect_vars(str(_condition), "eval", entry)
                    sub = _vn_new_entry()
                    if block:
                        _vn_walk_ast(block, sub)
                    entry["branch_assigns"].append(list(sub["assigns"]))
                    sub["assigns"] = []
                    _vn_merge_entry(entry, sub)
            elif cls == "While":
                _vn_collect_vars(str(getattr(node, "condition", "")), "eval", entry)
                _vn_walk_ast(node.block, entry)
            else:
                block = getattr(node, "block", None)
                if isinstance(block, _VN_LIST):
                    _vn_walk_ast(block, entry)

    def _vn_analyze_inputs(args, ap):
        """Единый список входов из двух источников: файла-списка и прямых аргументов.

        Разбор один и тот же — источник влияет только на то, ОТКУДА взялись строки
        путей, а не на то, что с ними делают. Файл-список: по пути на строку,
        UTF-8, пустые строки игнорируются; rstrip снимает CRLF, если список
        писала рука на Windows."""
        import io

        files = list(args.files)
        if args.files_from:
            with io.open(args.files_from, "r", encoding="utf-8") as f:
                files += [line.rstrip("\r\n") for line in f if line.strip()]
        if not files:
            ap.error("нужен --files-from <список> либо пути сцен аргументами")
        return files

    def _vn_analyze_command():
        import io
        import json

        ap = renpy.arguments.ArgumentParser()
        ap.add_argument("out")
        ap.add_argument("--files-from", dest="files_from", default=None,
                        metavar="FILE",
                        help="Файл со списком scene.rpy: по пути на строку, UTF-8.")
        ap.add_argument("files", nargs="*",
                        help="Пути scene.rpy аргументами (отладка одной сцены руками).")
        args = ap.parse_args()

        result = {"renpy": renpy.version_only, "files": {}}
        for fn in _vn_analyze_inputs(args, ap):
            entry = _vn_new_entry()
            try:
                with io.open(fn, "r", encoding="utf-8") as f:
                    filedata = f.read()
                renpy.parser.parse_errors = []
                stmts = renpy.parser.parse(fn, filedata)
                if stmts is None:
                    entry["errors"] = [str(e) for e in renpy.parser.parse_errors]
                else:
                    # Парсер добавляет неявный Return в конец файла — отрезаем его,
                    # иначе он ловится как «пустой авторский return».
                    if stmts and type(stmts[-1]).__name__ == "Return" \
                            and getattr(stmts[-1], "expression", None) is None:
                        stmts = stmts[:-1]
                    # Контракт scene.rpy: на верхнем уровне — только label.
                    for node in stmts:
                        if type(node).__name__ != "Label":
                            entry["errors"].append(
                                "line %s: стейтмент %s вне label запрещён в scene.rpy"
                                % (getattr(node, "linenumber", "?"), type(node).__name__)
                            )
                    if not entry["errors"]:
                        _vn_walk_ast(stmts, entry)
            except Exception as e:
                entry["errors"] = ["%s: %s" % (type(e).__name__, e)]
            result["files"][fn] = entry

        with io.open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        return False

    renpy.arguments.register_command("vn_analyze", _vn_analyze_command)
