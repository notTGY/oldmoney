import csv, html, json, re, time
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from schema import CSV_COLUMNS, format_gender, format_price


API = "https://api.nike.com"
CHANNEL = "d9a5bc42-4b9c-4976-858a-f159cf99c647"
WALL = (
    f"{API}/discover/product_wall/v1/marketplace/US/language/en/consumerChannelId/{CHANNEL}"
    "?path=/w/mens-clothing-6ymx6znik1&attributeIds=a00f0bb2-648b-4853-9559-4cd943b7d6c6,"
    "0f64ecc7-d624-4e91-b171-b83a03dd8550"
    "&queryType=PRODUCTS&anchor=0&count=24"
)
FEED = f"{API}/product_feed/threads/v2"
OUTPUT = "nike.csv"
HEADERS = {
    "nike-api-caller-id": "nike:dotcom:browse:wall.client:2.0",
    "Origin": "https://www.nike.com",
    "Referer": "https://www.nike.com/",
    "User-Agent": "Mozilla/5.0",
}

def fetch(url, retries=6):
    try:
        with urlopen(Request(url, headers=HEADERS), timeout=60) as response:
            return json.load(response)
    except Exception:
        if retries == 1: raise
        time.sleep(2 ** (6 - retries))
        return fetch(url, retries - 1)


def style_codes():
    codes, url = set(), WALL
    while url:
        page = fetch(url)
        for group in page["productGroupings"]:
            for product in group.get("products", []):
                if product.get("productType") == "APPAREL":
                    codes.add(product["productCode"])
        url = urljoin(API, page["pages"]["next"]) if page["pages"].get("next") else None
    return sorted(codes)


def product_feed(codes):
    filters = [("filter", "marketplace(US)"), ("filter", "language(en)"), ("filter", f"channelId({CHANNEL})")]
    for offset in range(0, len(codes), 24):
        batch = ",".join(codes[offset:offset + 24])
        url = f"{FEED}?{urlencode(filters + [('filter', f'productInfo.merchProduct.styleColor({batch})')])}"
        yield from fetch(url)["objects"]
        print(f"Fetched details for {min(offset + 24, len(codes))}/{len(codes)} products")


def clean_description(raw):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())


def looks(thread):
    info = thread["productInfo"][0]
    product = info["merchProduct"]
    content = info["productContent"]
    price = info["merchPrice"]
    description = content.get("description", "")
    materials = "; ".join(clean_description(item) for item in re.findall(
        r"<li[^>]*>([^<]*\d+%[^<]*)</li>", description, re.I))
    category = " / ".join(["APPAREL", *product.get("sportTags", [])])
    product_url = f"https://www.nike.com/t/{content['slug']}/{product['styleColor']}"
    nodes = (thread.get("publishedContent") or {}).get("nodes", [])
    media = nodes[0].get("nodes", []) if nodes else []
    for card in media:
        portrait = card.get("properties", {}).get("portrait", {})
        if card.get("subType") == "image" and portrait.get("view") in {"D", "E"}:
            yield {
                "image_url": portrait["url"],
                "product_id": product["styleColor"],
                "source": "nike",
                "product_name": content.get("fullTitle", ""),
                "price": format_price(price.get("currentPrice")),
                "currency": price.get("currency", ""),
                "category": category,
                "gender": format_gender(product.get("genders", [])),
                "color": content.get("colorDescription", ""),
                "description": clean_description(description),
                "materials": materials,
                "product_url": product_url,
            }


def main():
    rows = {row["image_url"]: row for item in product_feed(style_codes()) for row in looks(item)}
    with open(OUTPUT, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows.values())
    print(f"Wrote {len(rows)} images to {OUTPUT}")

if __name__ == "__main__":
    main()
