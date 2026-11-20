FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sulsul_server ./sulsul_server
ENV SULSUL_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8787
CMD ["python", "-m", "sulsul_server"]
