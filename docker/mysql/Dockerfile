FROM mysql:8.0

# Copy custom configuration
COPY my.cnf /etc/mysql/conf.d/tpch.cnf

# Copy initialization script
COPY init-db.sh /docker-entrypoint-initdb.d/

# Set environment for proper character set
ENV MYSQL_ROOT_PASSWORD=rootpass
ENV MYSQL_DATABASE=tpch
ENV MYSQL_USER=tpch_user
ENV MYSQL_PASSWORD=tpch_pass
