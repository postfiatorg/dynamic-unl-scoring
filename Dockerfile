FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY scoring_service ./scoring_service
COPY migrations ./migrations
COPY prompts ./prompts
# BGP routing table + AS names for ASN lookups (refresh quarterly)
COPY data/asn/ipasn_20260317.dat data/asn/asnames.json ./data/asn/
# DB-IP Lite Country database for geolocation (CC BY 4.0, refresh quarterly)
COPY data/geolocation/dbip-country-lite.mmdb ./data/geolocation/

EXPOSE 8000

CMD ["uvicorn", "scoring_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
