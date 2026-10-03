FROM --platform=linux/amd64 python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install "lightpanda==1.0.0"
WORKDIR /app
COPY gateway.py start.sh ./
RUN chmod +x start.sh
CMD ["./start.sh"]
