FROM container-registry.oracle.com/database/express:21.3.0-xe

# Copy initialization script
COPY init.sql /docker-entrypoint-initdb.d/

# Set environment variables
ENV ORACLE_PWD=OraclePass123
ENV ORACLE_CHARACTERSET=AL32UTF8

# Note: Oracle Express Edition has built-in memory limits
# SGA is automatically managed within XE constraints
