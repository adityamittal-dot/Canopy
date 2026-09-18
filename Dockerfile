FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SECRET_KEY only needs to be *set* (any value) for collectstatic to import
# settings.py at build time - the real value is injected at runtime.
RUN SECRET_KEY=build-time-placeholder python manage.py collectstatic --noinput

EXPOSE 8000

# Shell form (not exec-form JSON) so $PORT actually expands - Railway
# assigns it dynamically rather than always using 8000. Migrations run on
# every start; safe since Django migrations are idempotent.
#
# --timeout 300: gunicorn's default worker timeout is 30s, but /analyze/
# clones and parses a caller-supplied repo synchronously in-request - a
# real-world repo (not just the tiny ones used in dev) can easily take
# longer than that (clone_repo's own subprocess timeout already allows up
# to 120s). Without this, gunicorn SIGKILLs the worker mid-analysis and
# Render's proxy surfaces that as a 502, well before the app itself would
# ever time out or error.
CMD python manage.py migrate --noinput && gunicorn canopy.wsgi:application --bind 0.0.0.0:${PORT:-8000} --timeout 300
