import re
import json
import time
import requests
from bs4 import BeautifulSoup

SITE = "https://analyst-assessment-production.up.railway.app"


def get_soup(path, retries=4):
    """Fetch a page, retrying on network errors with a growing wait."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(f"{SITE}{path}", timeout=30)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            if attempt == retries:
                raise
            wait = 2 * attempt
            print(f"  ! {path} failed ({e.__class__.__name__}), retry {attempt} in {wait}s")
            time.sleep(wait)


def profile_links(soup):
    """Return profile paths like /communities/<slug> found on a page."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0].rstrip("/")
        if href.startswith("/communities/") and href not in links:
            links.append(href)
    return links


def discover_profiles():
    """Collect every profile link from all directory pages + the homepage."""
    found = {}  # path -> where we found it

    # Walk directory pages by following pagination links (?page=N)
    to_visit, visited = ["/communities"], set()
    while to_visit:
        page = to_visit.pop(0)
        if page in visited:
            continue
        visited.add(page)
        soup = get_soup(page)
        for link in profile_links(soup):
            found.setdefault(link, "directory")
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("/communities?page=") and a["href"] not in visited:
                to_visit.append(a["href"])

    # The homepage can announce communities not yet in the directory
    for link in profile_links(get_soup("/")):
        found.setdefault(link, "homepage")

    return found


def parse_profile(path):
    """Extract name, address and care offerings from one profile page."""
    soup = get_soup(path)
    data = {"slug": path.split("/")[-1], "url": f"{SITE}{path}"}
    data["name"] = soup.find("h1").get_text(strip=True)

    # The <dl class="detail"> holds label (<dt>) / value (<dd>) pairs
    detail = soup.find("dl", class_="detail")
    fields = {}
    for dt in detail.find_all("dt"):
        fields[dt.get_text(strip=True).lower()] = dt.find_next_sibling("dd")

    # Address: "street <br/> City, ST 12345"
    lines = list(fields["address"].stripped_strings)
    data["street"] = " ".join(lines[:-1])
    m = re.match(r"^(.*),\s*([A-Z]{2})\s+(\d{5})", lines[-1])
    data["city"], data["state"], data["zip"] = m.groups() if m else (lines[-1], "", "")

    care = fields.get("care offerings")
    data["care_offerings"] = (
        [b.get_text(strip=True) for b in care.find_all("span", class_="badge")] if care else []
    )
    data["administrator"] = fields["administrator"].get_text(strip=True) if "administrator" in fields else ""
    data["phone"] = fields["phone"].get_text(strip=True) if "phone" in fields else ""
    return data


def scrape():
    locations = []
    for path, source in discover_profiles().items():
        try:
            loc = parse_profile(path)
            loc["found_on"] = source
            locations.append(loc)
        except Exception as e:
            print(f"  ! Could not parse {path}: {e}")
        time.sleep(0.2)  # be polite to the server
    return locations


if __name__ == "__main__":
    locations = scrape()
    with open("website_locations.json", "w") as f:
        json.dump(locations, f, indent=2)

    print(f"Scraped {len(locations)} locations -> website_locations.json")
    for loc in locations:
        print(f"  [{loc['found_on']:9}] {loc['name']} | {loc['street']}, "
              f"{loc['city']}, {loc['state']} {loc['zip']} | {', '.join(loc['care_offerings'])}")