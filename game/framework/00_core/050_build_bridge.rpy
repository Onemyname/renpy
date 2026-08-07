# Build-bridge (G24): анализ авторских scene.rpy ПАРСЕРОМ САМОГО Ren'Py.
# Компилятор (tools/vn) вызывает: renpy.exe <root> vn_analyze <out.json> <файлы...>
# Команда исполняется после init, до главного цикла; return False = не запускать игру.
# Регексы по .rpy запрещены архитектурой — это единственный легальный способ разбора.

init python:

    def _vn_walk_ast(nodes, entry):
        for node in nodes:
            cls = type(node).__name__
            line = getattr(node, "linenumber", 0)
            if cls == "Label":
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
            elif cls == "Menu":
                captions = []
                for item in node.items:
                    caption, _condition, block = item[0], item[1], item[2]
                    captions.append(caption)
                    if block:
                        _vn_walk_ast(block, entry)
                entry["menus"].append({"line": line, "items": captions})
            elif cls == "If":
                for _condition, block in node.entries:
                    _vn_walk_ast(block, entry)
            elif cls == "While":
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
                "menus": [], "says": 0, "errors": [],
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
