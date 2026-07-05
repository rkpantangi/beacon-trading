FROM python:3.12-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY trading_app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project to the container
COPY . .

# Expose Fly.io default port
EXPOSE 8080

# Run uvicorn from the root context, setting pythonpath and app directory
ENV PYTHONPATH=/app/trading_app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "trading_app"]
