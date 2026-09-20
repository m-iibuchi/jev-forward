# migrations — 前進のみのマイグレーション

- ファイル名は `NNN_<snake_name>.sql`。`NNN` は適用後の `schema_version.version` と一致させる（版1は `../schema.sql` なので 002 から）
- 各ファイルは `BEGIN IMMEDIATE;` で始まり、`INSERT INTO schema_version (version, applied_at) VALUES (NNN, …);` と `COMMIT;` で終わる
- 許可：`CREATE TABLE` / `CREATE INDEX` / `CREATE TRIGGER` / `ALTER TABLE … ADD COLUMN`
- 禁止：既存行の値を変える操作すべて、凍結テーブルのトリガーを外す操作
- 規約の全文は `docs/detailed/01-凍結ログ.md` 4.4。テストは T01-25
