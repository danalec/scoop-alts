import requests
import re

url = "https://github.com/Alex313031/Thorium-Win/releases"
response = requests.get(url)
content = response.text

regex = r"releases/tag/M([\d.]+)"
matches = re.findall(regex, content)
print("Matches:", matches)
