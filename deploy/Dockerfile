# jevfwd のイメージ。M1 では dev ターゲットだけを使う（開発・テストをホストに依存させない）。
# 本番ターゲット（supervisord で fetcher / bundler / judge_worker / heartbeat / digest を回す）は M5 で足す。
FROM python:3.11-slim AS dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

WORKDIR /app

# 依存だけを先に入れる（ソースは実行時に bind mount する）。editable install の参照先 /app/src は
# マウント後も同じパスなので、コンテナ内の jevfwd はホスト側の編集をそのまま見る。
COPY pyproject.toml ./
RUN mkdir -p src/jevfwd \
 && printf '"""build 時の仮パッケージ。実行時は bind mount の src/jevfwd で置き換わる。"""\n' > src/jevfwd/__init__.py \
 && pip install -e ".[dev]" \
 && rm -rf src

CMD ["pytest"]
