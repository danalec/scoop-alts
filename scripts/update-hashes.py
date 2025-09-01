#!/usr/bin/env python3
"""Manual hash updater for ungoogled-chromium"""

import json
import hashlib
from urllib.request import urlopen
from pathlib import Path

def calculate_hash(url):
    """Calculate SHA256 hash from URL"""
    try:
        print(f"Downloading: {url}")
        with urlopen(url) as response:
            sha256 = hashlib.sha256()
            for chunk in iter(lambda: response.read(4096), b""):
                sha256.update(chunk)
            return sha256.hexdigest()
    except Exception as e:
        print(f"Error: {e}")
        return None

def main():
    bucket_path = Path(__file__).parent.parent / "bucket" / "ungoogled-chromium.json"
    
    with open(bucket_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    version = data['version']
    print(f"Current version: {version}")
    
    # Update 64-bit hash
    url_64 = f"https://github.com/ungoogled-software/ungoogled-chromium-windows/releases/download/{version}/ungoogled-chromium_{version}_windows_x64.zip"
    hash_64 = calculate_hash(url_64)
    
    # Update 32-bit hash  
    url_32 = f"https://github.com/ungoogled-software/ungoogled-chromium-windows/releases/download/{version}/ungoogled-chromium_{version}_windows_x86.zip"
    hash_32 = calculate_hash(url_32)
    
    if hash_64 and hash_32:
        data['architecture']['64bit']['hash'] = hash_64
        data['architecture']['32bit']['hash'] = hash_32
        
        with open(bucket_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        print(f"Updated 64-bit hash: {hash_64}")
        print(f"Updated 32-bit hash: {hash_32}")
        print("JSON file updated successfully!")
    else:
        print("Failed to calculate one or more hashes")

if __name__ == "__main__":
    main()