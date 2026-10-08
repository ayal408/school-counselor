"""Run explicitly on a machine with approved network access; inference stays offline."""
from pathlib import Path
from huggingface_hub import snapshot_download
# Download is explicit; installed model directory is mounted read-only for offline inference.
snapshot_download('Systran/faster-whisper-small',revision='main',local_dir=str(Path(__file__).resolve().parents[1]/'models'/'whisper'))
