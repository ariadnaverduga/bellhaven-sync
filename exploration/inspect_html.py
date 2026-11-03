import requests
from bs4 import BeautifulSoup

SITE = "https://analyst-assessment-production.up.railway.app"

# 1) Links found on the directory page
html = requests.get(f"{SITE}/communities").text
soup = BeautifulSoup(html, "html.parser")
print("=== Links on /communities ===")
for a in soup.find_all("a", href=True):
    print(a["href"])

# 2) Raw HTML of one profile page (main content only)
html = requests.get(f"{SITE}/communities/bellhaven-of-chesterton").text
soup = BeautifulSoup(html, "html.parser")
main = soup.find("main") or soup.body
print("\n=== Profile page HTML ===")
print(main.prettify())