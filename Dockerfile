FROM python:3.11-slim

WORKDIR /opt/render/project/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 FLASK_ENV=production
EXPOSE 10000

# Target a global Flask app object defined in app.py like: app = Flask(__name__)
ENV PYTHONUNBUFFERED=1 FLASK_ENV=production PYTHONPATH=/opt/render/project/src
EXPOSE 10000
CMD bash -lc "gunicorn --chdir /opt/render/project/src -w 2 -k gthread -b 0.0.0.0:${PORT:-10000} app:app"
