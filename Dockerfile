FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Se genera todo desde los CSV originales: tablas, reporte de calidad y dashboard
RUN python sql/run_sql.py \
 && python python/analysis.py \
 && python visualization/build_dashboard.py

ENV AGENT_HOST=0.0.0.0
EXPOSE 8080 8000

# Dashboard en el puerto 8080 y agente en el 8000
CMD ["sh", "-c", "python -m http.server 8080 --directory visualization & python agent/server.py"]
