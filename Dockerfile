FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ffmpeg  && \
    rm -rf /var/lib/apt/lists/*

ENV POETRY_VERSION=2.1
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

# 3. Workdir inside the container
WORKDIR /app

COPY . /app

RUN poetry config virtualenvs.create false \
 && poetry install --no-interaction --no-ansi


EXPOSE 8443

CMD ["uvicorn", "bunkabot.main:app", "--host", "0.0.0.0", "--port", "8443", "--reload"]
