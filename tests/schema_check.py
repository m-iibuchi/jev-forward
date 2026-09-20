"""受入テスト用の最小 JSON Schema バリデータ（05-state構築 8章）。

`jsonschema` を依存に入れないために、`docs/contracts/state.v2.schema.json` が
実際に使っているキーワードだけを実装する：
`type` `const` `pattern` `required` `additionalProperties` `items` `properties` `minLength`。

実装（`src/jevfwd/state/`）とは独立に書く。実装の自己検査（builder._self_check）が
通っても、契約に合っていなければここで落ちる。
"""

import re

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def validate(instance, schema: dict, path: str = "$") -> list[str]:
    """schema 違反の説明を並べて返す（空なら valid）。"""
    errors: list[str] = []
    _check(instance, schema, path, errors)
    return errors


def assert_valid(instance, schema: dict, path: str = "$") -> None:
    errors = validate(instance, schema, path)
    assert errors == [], "\n".join(errors)


def _matches_type(value, name: str) -> bool:
    expected = _TYPES[name]
    if name in ("integer", "number") and isinstance(value, bool):
        return False                              # JSON の true は数値ではない
    if name == "integer":
        return isinstance(value, int)
    return isinstance(value, expected)


def _check(value, schema: dict, path: str, errors: list[str]) -> None:
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        for name in names:
            if name not in _TYPES:
                errors.append(f"{path}: 未対応の type {name!r}（schema_check を拡張する）")
                return
        if not any(_matches_type(value, name) for name in names):
            errors.append(f"{path}: type が {names} でない（{type(value).__name__}）")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const {schema['const']!r} でない（{value!r}）")
    if isinstance(value, str):
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: pattern {schema['pattern']!r} に一致しない（{value!r}）")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: minLength {schema['minLength']} 未満")
    if isinstance(value, dict):
        _check_object(value, schema, path, errors)
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{index}]", errors)


def _check_object(value: dict, schema: dict, path: str, errors: list[str]) -> None:
    properties = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in value:
            errors.append(f"{path}: 必須キー {key!r} が無い")
    extra = schema.get("additionalProperties", True)
    for key, item in value.items():
        if key in properties:
            _check(item, properties[key], f"{path}.{key}", errors)
        elif extra is False:
            errors.append(f"{path}: 余分なキー {key!r}")
        elif isinstance(extra, dict):
            _check(item, extra, f"{path}.{key}", errors)
