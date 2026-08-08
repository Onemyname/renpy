"""Реестр лицензий (license_registry@1): покрытие деклараций, запреты game_use
и nsfw_allowed — юридический гейт коммерческой 18+ сборки."""

import shutil

from vn.assets.licenses import load_registry, validate_licenses

from conftest import REPO_ROOT

REGISTRY = """\
schema: license_registry@1
assets:
  ok_asset:
    title: "Clean Product"
    vendor: daz
    sku: "1"
    license_type: daz_standard
    game_use: true
    nsfw_allowed: true
  no_game:
    title: "Editorial Only"
    vendor: daz
    license_type: custom
    game_use: false
    nsfw_allowed: true
  sfw_only:
    title: "No Adult Use"
    vendor: daz
    license_type: daz_standard
    game_use: true
    nsfw_allowed: false
"""


def _mk_root(tmp_path):
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "tools" / "schemas", root / "tools" / "schemas")
    (root / "content").mkdir()
    (root / "content" / "licenses.yaml").write_text(REGISTRY, encoding="utf-8")
    return root


def _decl(root, name, license_ids, output="png/cg/ch01/shot.png"):
    p = root / "assets_src" / "daz" / f"{name}.render.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    lic = ("license: [%s]\n" % ", ".join(license_ids)) if license_ids else ""
    p.write_text(
        "schema: daz_render@1\n"
        f"id: cg/ch01/{name}\n"
        f"source: daz/{name}/scene.duf\n"
        f"output: {output}\n"
        f"{lic}"
        "render: {resolution: [1920, 1080], renderer: iray, camera: cam}\n",
        encoding="utf-8")
    return p


def test_registry_loads(tmp_path):
    root = _mk_root(tmp_path)
    entries = load_registry(root)
    assert set(entries) == {"ok_asset", "no_game", "sfw_only"}


def test_clean_declaration_passes(tmp_path):
    root = _mk_root(tmp_path)
    _decl(root, "clean", ["ok_asset"])
    rep = validate_licenses(root)
    assert rep.errors == [] and rep.declarations == 1 and rep.unlicensed == []


def test_unknown_license_reference_is_error(tmp_path):
    root = _mk_root(tmp_path)
    _decl(root, "ghost", ["not_in_registry"])
    rep = validate_licenses(root)
    assert any("не найден" in e for e in rep.errors)


def test_game_use_false_blocks(tmp_path):
    root = _mk_root(tmp_path)
    _decl(root, "editorial", ["no_game"])
    rep = validate_licenses(root)
    assert any("game_use: false" in e for e in rep.errors)


def test_nsfw_asset_gate(tmp_path):
    """Ассет без права на adult-использование не пускается в nsfw-выход."""
    root = _mk_root(tmp_path)
    _decl(root, "sfw_in_nsfw", ["sfw_only"], output="png/cg/nsfw/scene.png")
    rep = validate_licenses(root)
    assert any("nsfw_allowed: false" in e for e in rep.errors)

    # Тот же ассет в обычной зоне — законно
    root2 = _mk_root(tmp_path / "second")
    _decl(root2, "sfw_ok", ["sfw_only"], output="png/cg/ch01/scene.png")
    assert validate_licenses(root2).errors == []


def test_missing_license_field_warns_not_fails(tmp_path):
    root = _mk_root(tmp_path)
    _decl(root, "untracked", [])
    rep = validate_licenses(root)
    assert rep.errors == []
    assert rep.unlicensed == ["assets_src/daz/untracked.render.yaml"]
    assert any("без поля license" in w for w in rep.warnings)


def test_repo_registry_is_schema_valid(repo_root):
    """Боевой content/licenses.yaml обязан проходить схему (иначе гейт слеп)."""
    rep = validate_licenses(repo_root)
    assert rep.errors == []
    assert rep.entries >= 1
