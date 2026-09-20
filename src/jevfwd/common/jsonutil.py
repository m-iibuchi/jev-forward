"""JSON の正規化。`*_json` 列はこの書式で作る（00-共通規約 5章）。

生保存する列（request_json / response_json / question_versions.json /
state_versions.spec / bundles.state_json）には使わない。
"""

import json


def canonical(obj: object) -> str:
    """キー順を揃えた最小表現の JSON 文字列。配列の順序は保つ。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
