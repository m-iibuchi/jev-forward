"""jevfwd の例外階層（00-共通規約 6章）。

sqlite3 の例外は包まない（どの制約に当たったかをメッセージに残すため）。
"""


class JevfwdError(Exception):
    """全例外の基底。CLI はこれを終了コード 1 に変換する。"""


class ConfigError(JevfwdError):
    """設定ファイル・版ファイル・秘密の不備。"""


class StoreError(JevfwdError):
    """DB 層の不整合（トリガー欠落、マイグレーションの欠番など）。"""


class SchemaMismatchError(StoreError):
    """schema_version がコードの期待と違う。CLI は終了コード 3。"""


class FetchError(JevfwdError):
    """取得層の失敗（M2）。"""


class JudgeError(JevfwdError):
    """判定層の失敗（M4）。未凍結の版を使おうとした場合を含む。"""
