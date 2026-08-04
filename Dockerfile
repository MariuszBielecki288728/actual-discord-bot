FROM python:3.13.14-slim AS python-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"


FROM python-base AS builder-base

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    curl \
    git \
    build-essential \
    tesseract-ocr \
    tesseract-ocr-pol \
    libtesseract-dev

ENV POETRY_VERSION=2.4.1
RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR $PYSETUP_PATH
COPY . .

RUN poetry install --only main
RUN poetry build


FROM python-base AS development

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    tesseract-ocr \
    tesseract-ocr-pol \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder-base $POETRY_HOME $POETRY_HOME
COPY --from=builder-base $PYSETUP_PATH $PYSETUP_PATH


WORKDIR $PYSETUP_PATH
RUN poetry install

WORKDIR /app
COPY . .

CMD ["actual_discord_bot/bot.py"]


FROM development AS testing

WORKDIR $PYSETUP_PATH
RUN poetry install --with tests

WORKDIR /app


FROM python-base AS production

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    tesseract-ocr \
    tesseract-ocr-pol \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder-base $VENV_PATH $VENV_PATH
COPY --from=builder-base $PYSETUP_PATH/dist .
# The builder virtualenv already contains the lockfile-resolved VCS dependency.
# Avoid asking pip in the Git-free production image to clone it again.
RUN pip install --no-deps *.whl

WORKDIR /app

CMD ["python", "-u", "-m", "actual_discord_bot.bot"]
