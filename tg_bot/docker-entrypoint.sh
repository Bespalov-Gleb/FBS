#!/bin/sh
set -e
mkdir -p /app/uploads /app/outputs
chown -R botuser:botuser /app/uploads /app/outputs
exec gosu botuser "$@"
