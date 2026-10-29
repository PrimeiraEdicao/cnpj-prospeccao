FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    APP_ENV=production AUTH_MODE=supabase DATA_ROOT=/var/lib/cnpj
WORKDIR /app
COPY requirements.lock ./
RUN pip install --only-binary=pyarrow -r requirements.lock \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /var/lib/cnpj/data && chown -R app:app /var/lib/cnpj
COPY --chown=app:app app.py ./
COPY --chown=app:app src ./src
COPY --chown=app:app assets ./assets
COPY --chown=app:app config ./config
COPY --chown=app:app data ./data
COPY --chown=app:app .streamlit/config.toml ./.streamlit/config.toml
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)" || exit 1
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
