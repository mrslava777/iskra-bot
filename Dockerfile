FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the bot
COPY . .

# Persist the SQLite database on the container disk (./data survives restarts
# on container hosts that keep the working directory). config.py auto-detects
# /data volume if the host provides one; otherwise it uses ./iskra.db here.
ENV PYTHONUNBUFFERED=1

# Telegram bot runs via long polling — no exposed port needed.
CMD ["python", "bot.py"]
