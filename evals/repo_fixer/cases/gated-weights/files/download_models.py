"""Downloads the generator's checkpoint into models/ (the README's only download link)."""
from pathlib import Path

from huggingface_hub import hf_hub_download

Path("models").mkdir(exist_ok=True)
print("downloaded", hf_hub_download("meta-llama/Llama-3.2-1B", "config.json", local_dir="models"))
