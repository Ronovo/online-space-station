# The coverage reports only show what the tests reach, so failing tests or low coverage still build the image.
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS python-coverage
WORKDIR /src
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
RUN python -m coverage run -m pytest -p no:cacheprovider ; \
    python -m coverage html --fail-under=0 ; mkdir -p coverage/python ; \
    python -m coverage json --fail-under=0 -o coverage.json ; \
    python coverage-index/tools/functions.py coverage.json coverage/python/functions.json

FROM node:24-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS js-coverage
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npx vitest run --coverage ; mkdir -p coverage/js ; cat coverage-index/istanbul.css >> coverage/js/base.css

FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REPO_URL=https://github.com/Ronovo/online-space-station.git \
    BUILD_CMD="pip install --no-cache-dir --user -q -r requirements.txt"

WORKDIR /app

COPY docker/git-sync.sh /usr/local/bin/git-sync
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && chmod +x /usr/local/bin/git-sync

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0 \
    && useradd --create-home --uid 1000 space

COPY . .
COPY coverage-index/index.html coverage/
COPY coverage-reports.json coverage/reports.json
COPY --from=python-coverage /src/coverage/python coverage/python
COPY --from=js-coverage /src/coverage/js coverage/js

# Accounts, characters and the generated session key live in /app/instance.
RUN mkdir -p instance && chown -R space /app
USER space

VOLUME ["/app/instance"]
EXPOSE 5000

# One worker: with no SPACE_ONLINE_SECRET_KEY set, several workers would race to generate the key file.
ENTRYPOINT ["git-sync"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "space_online.webapp:create_app()"]
