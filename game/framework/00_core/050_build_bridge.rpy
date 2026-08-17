# Build-bridge (G24): анализ авторских scene.rpy ПАРСЕРОМ САМОГО Ren'Py.
# Компилятор (tools/vn) вызывает: renpy.exe <root> vn_analyze <out.json> <файлы...>
# Команда исполняется после init, до главного цикла; return False = не запускать игру.
# Регексы по .rpy запрещены архитектурой — это единственный легальный способ разбора.

init python:

    import ast as _vn_ast
    import re as _vn_re

    # Управляемые named stores (зеркало vars@1.store): только их атрибуты едут в
    # сейв и миграции. Обращение к атрибуту вне реестра — молчаливый фантом (G5).
    _VN_STORE_RE = _vn_re.compile(r"^(g|ch\d{2}|mech_[a-z0-9_]+|dlc_[a-z0-9_]+|persistent)$")

    def _vn_collect_vars(source, mode, entry):
        """Извлечь чтения/записи атрибутов управляемых stores из python-фрагмента
        или выражения-условия. Классификация по ast-контексту: Store=запись,
        Load=чтение. Непарсящийся фрагмент молча пропускается (не валим анализ)."""
        if not source:
            return
        try:
            tree = _vn_ast.parse(source, mode=mode)
        except (SyntaxError, ValueError):
            return
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
                if isinstance(payload, dict) and stmt.split(" ")[0] in ("play", "queue"):
                    entry["audio_refs"].append({
                        "line": line, "stmt": stmt,
                        "file": payload.get("file"),
                        "channel": payload.get("channel"),
                    })
            elif cls == "Label":
                entry["labels"].append({"name": node.name, "line": line})
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
                })
            elif cls == "Python":
                src = getattr(getattr(node, "code", None), "source", "") or ""
                if src.strip().startswith("vn_menu"):
                    entry["menu_markers"].append({"line": line, "source": src.strip()})
                _vn_collect_vars(src, "exec", entry)   # $ ch01.x = True / python:-блоки
            elif cls == "Menu":
                captions = []
                conditions = []
                for item in node.items:
                    caption, condition, block = item[0], item[1], item[2]
                    captions.append(caption)
                    conditions.append(str(condition))
                    _vn_collect_vars(str(condition), "eval", entry)
                    if block:
                        _vn_walk_ast(block, entry)
                entry["menus"].append({"line": line, "items": captions,
                                       "conditions": conditions})
            elif cls == "If":
                for _condition, block in node.entries:
                    _vn_collect_vars(str(_condition), "eval", entry)
                    _vn_walk_ast(block, entry)
            elif cls == "While":
                _vn_collect_vars(str(getattr(node, "condition", "")), "eval", entry)
                _vn_walk_ast(node.block, entry)
            else:
                block = getattr(node, "block", None)
                if isinstance(block, list):
                    _vn_walk_ast(block, entry)

    def _vn_analyze_command():
        import io
        import json

        ap = renpy.arguments.ArgumentParser()
        ap.add_argument("out")
        ap.add_argument("files", nargs="+")
        args = ap.parse_args()

        result = {"renpy": renpy.version_only, "files": {}}
        for fn in args.files:
            entry = {
                "labels": [], "jumps": [], "calls": [], "returns": [],
                "menus": [], "says": 0, "say_list": [], "menu_markers": [],
                "var_reads": [], "var_writes": [], "errors": [],
                "image_refs": [], "audio_refs": [],
            }
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
