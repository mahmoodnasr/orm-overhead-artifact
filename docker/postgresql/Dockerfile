FROM postgres:14

# Install required tools
RUN apt-get update && apt-get install -y \
    postgresql-contrib \
    && rm -rf /var/lib/apt/lists/*

# Copy custom configuration
COPY postgresql.conf /etc/postgresql/postgresql.conf

# Set up PostgreSQL to use custom config
CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
