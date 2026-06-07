FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /srv/carecircle

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg unzip \
    && curl -fsSL https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip -o /tmp/vosk-model.zip \
    && unzip -q /tmp/vosk-model.zip -d /opt \
    && mv /opt/vosk-model-small-en-in-0.4 /opt/vosk-model \
    && rm -rf /var/lib/apt/lists/* /tmp/vosk-model.zip

COPY automation/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt uvicorn==0.30.6

COPY automation/app ./app
COPY assets ./assets

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
