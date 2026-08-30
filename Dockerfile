# Use the official Playwright Python image. It has Python and all required browser dependencies preloaded.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

# Set working directory inside the container
WORKDIR /app

# Copy requirements file first to take advantage of Docker cache
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY . .

# Expose default port
EXPOSE 5000

# Run the Flask app with Gunicorn, dynamically binding to Render's allocated PORT
CMD gunicorn -w 1 -b 0.0.0.0:$PORT app:app
