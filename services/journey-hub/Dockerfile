FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY services/journey-hub/ ./

ENV PYTHONPATH="/app:${PYTHONPATH}"

EXPOSE 8001

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
