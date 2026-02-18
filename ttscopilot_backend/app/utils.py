import uuid
import os

def sanitize_filename(filename: str) -> str:
    return str(uuid.uuid4()) + os.path.splitext(filename)[1]