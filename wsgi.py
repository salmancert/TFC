"""WSGI entry point for production serving.

Used by gunicorn or waitress. Unlike running app.py directly, this never
trains: it loads the model built by `python cli.py train` and fails loudly if
there isn't one, so a server restart can't quietly kick off a 30-second
training run in every worker process.

    gunicorn  --workers 3 --preload --bind 0.0.0.0:8000 wsgi:application
    waitress-serve --listen=0.0.0.0:8000 wsgi:application

`--preload` matters: it loads the model once before forking, so the workers
share those pages copy-on-write instead of holding a few hundred megabytes
each.
"""
import logging
import sys

from app import ModelNotBuiltError, create_app

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')

try:
    application = create_app(allow_training=False)
except ModelNotBuiltError as exc:
    sys.stderr.write('\n%s\n\n' % exc)
    raise

# Common alias, so `wsgi:app` works too.
app = application
