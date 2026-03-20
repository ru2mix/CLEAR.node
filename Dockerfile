FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV HOST="0.0.0.0"
ENV PORT=8001
VOLUME ["/app/data", "/app/Logs"]
EXPOSE $PORT
CMD ["python", "main.py"]