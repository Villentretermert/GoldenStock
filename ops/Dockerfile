FROM postgres:17.7
RUN apt-get update && apt-get install -y --no-install-recommends restic python3-psycopg2 \
    && rm -rf /var/lib/apt/lists/*
COPY recovery.py /opt/goldenstock/recovery.py
ENV RESTIC_REPOSITORY=/repository RESTIC_PASSWORD_FILE=/run/secrets/repository_password RESTIC_CACHE_DIR=/scratch/cache
ENTRYPOINT ["/usr/bin/python3", "/opt/goldenstock/recovery.py"]
