FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY scoring_service ./scoring_service
COPY migrations ./migrations
COPY prompts ./prompts

EXPOSE 8000

CMD ["uvicorn", "scoring_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
