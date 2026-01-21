FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

COPY backend/ /app/

CMD ["python", "-m", "jobs.worker"]