FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Non-root, иначе root в контейнере = root на volume-файлах при bind-mount.
RUN useradd --system --uid 1000 --create-home app \
    && mkdir -p /app/data /app/backups \
    && chown -R app:app /app
USER app

CMD ["python", "bot.py"]
