import io
import sys
import zipfile
import requests


def list_zip_contents(url: str):
    print(f"Downloading from {url}...")
    try:
        r = requests.get(url, stream=True)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for info in z.infolist():
                print(f"  {info.filename} ({info.file_size} bytes)")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else ""
    if not target_url:
        target_url = (
            "https://github.com/Alex313031/Thorium-Win/releases/download/"
            "M138.0.7204.300/Thorium_AVX2_138.0.7204.300.zip"
        )
    print("URL:", target_url)
    list_zip_contents(target_url)
