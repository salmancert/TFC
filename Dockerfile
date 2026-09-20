# Runs the forecaster as an internal web service.
# The image contains code only -- your expense export, trained model and fare
# cache are mounted in at runtime, so no company data is ever baked into a
# layer or pushed to a registry.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TCF_DATA_DIR=/data \
    TCF_MODELS_DIR=/models

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py cli.py wsgi.py ./
COPY travel_cost_forecasting/ ./travel_cost_forecasting/
COPY tools/ ./tools/

# Run as a non-root user; it needs to write the model and the fare cache only.
RUN useradd --create-home --uid 10001 tcf \
    && mkdir -p /data /models \
    && chown -R tcf:tcf /data /models /app
USER tcf

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status==200 else 1)"

# --preload loads the model once before forking so workers share it.
CMD ["gunicorn", "--workers", "3", "--threads", "2", "--preload", \
     "--bind", "0.0.0.0:8000", "--timeout", "60", \
     "--access-logfile", "-", "--error-logfile", "-", "wsgi:application"]
