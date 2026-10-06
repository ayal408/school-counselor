import os

def required(name, minimum=32):
    value = os.environ.get(name, "")
    if len(value) < minimum:
        raise RuntimeError(f"{name} must be configured ({minimum}+ characters)")
    return value

JWT_SECRET = required("JWT_SECRET")
INTERNAL_SERVICE_KEY = required("INTERNAL_SERVICE_KEY")
DATA_ENCRYPTION_KEY = required("DATA_ENCRYPTION_KEY")
DATABASE_URL = os.environ["DATABASE_URL"]
