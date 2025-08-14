FROM python:3.11-slim
WORKDIR /opt/render/project/src
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1 FLASK_ENV=production
EXPOSE 10000

# If your app has: app = Flask(__name__)
# CMD bash -lc "gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT:-10000} app:app"

# If your app uses a factory: def create_app(): return app
CMD bash -lc "gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT:-10000} 'app:create_app()'"
