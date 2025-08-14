FROM python:3.11-slim

WORKDIR /opt/render/project/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 FLASK_ENV=production
EXPOSE 10000

# Target a global Flask app object defined in app.py like: app = Flask(__name__)
CMD bash -lc "gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT:-10000} app:app"
