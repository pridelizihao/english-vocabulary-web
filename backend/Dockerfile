FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
# The seed commands read these bundled word lists; keep the paths relative to
# the image workdir so they behave like a local checkout.
COPY data/samples ./data/samples
COPY data/imports ./data/imports
RUN mkdir -p /app/db /app/staticfiles

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_demo && python manage.py seed_wordlists && python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120"]
