
import os
import logging
import zipfile
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

os.makedirs("Logs", exist_ok=True)
log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler = TimedRotatingFileHandler("Logs/full.log", when="midnight", interval=1, backupCount=0, encoding="utf-8")
file_handler.setFormatter(log_formatter)

def custom_namer(default_name):
    directory, filename = os.path.dirname(default_name), os.path.basename(default_name)
    parts = filename.split('.')
    if len(parts) >= 3:
        try: return os.path.join(directory, f"{datetime.strptime(parts[-1], '%Y-%m-%d').strftime('%d%m%Y')}_full.log.zip")
        except ValueError: pass
    return default_name + ".zip"

def custom_rotator(source, dest):
    with open(source, 'rb') as f_in:
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zipf: zipf.writestr("full.log", f_in.read())
    os.remove(source)

file_handler.namer, file_handler.rotator = custom_namer, custom_rotator
logger = logging.getLogger("CLEAR_NODE")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(logging.StreamHandler())