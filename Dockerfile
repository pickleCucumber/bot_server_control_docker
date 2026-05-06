FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*


RUN curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /usr/share/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/11/prod bullseye main" > /etc/apt/sources.list.d/mssql-release.list

RUN apt-get update \
    && apt-get remove -y unixodbc-common odbcinst || true

RUN ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17

RUN apt-get install -y --no-install-recommends \
    unixodbc \
    unixodbc-dev \
    gcc \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY logic.py .

ENV PYTHONUNBUFFERED=1

# Запускаем бот
CMD ["python", "bot.py"]
