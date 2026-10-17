FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py serve.py ./
COPY public ./public
EXPOSE 8080
CMD ["python", "serve.py"]
