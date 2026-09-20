"""凍結ログ（追記専用の SQLite）。書き込みは repo の INSERT だけ、読み取りは queries。

他モジュールは sqlite3 を直接触らない。詳細設計は docs/detailed/01-凍結ログ.md。
"""
