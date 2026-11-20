FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY simslink_server ./simslink_server
ENV SIMSLINK_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8787
CMD ["python", "-m", "simslink_server"]
