web: newrelic-admin run-program gunicorn -b "0.0.0.0:$PORT" app:app --preload --log-file=-
worker: python worker.py