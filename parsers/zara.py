import csv
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CATALOG_API = "https://www.zara.com/us/en/category/2443335/products?ajax=true"
DETAIL_API = "https://www.zara.com/us/en/products-details"
OUTPUT = "zara.csv"
HEADERS = {
    "Referer": "https://www.zara.com/us/en/man-all-products-l7465.html?v1=2443335",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
}
COLUMNS = [
    "image_url", "product_id", "source", "product_name", "price", "currency",
    "category", "gender", "color", "description", "materials", "product_url",
]


def fetch(url):
    with urlopen(Request(url, headers=HEADERS), timeout=60) as response:
        return json.load(response)


def products():
    catalog = fetch(CATALOG_API)
    discovered = (
        product
        for group in catalog["productGroups"]
        for element in group["elements"]
        for product in element.get("commercialComponents", [])
    )
    by_reference = {}
    for product in discovered:
        if product.get("kind") == "Wear":
            by_reference.setdefault(product["reference"], product["id"])

    ids = list(by_reference.values())
    for offset in range(0, len(ids), 10):
        params = [("productIds", product_id) for product_id in ids[offset:offset + 10]]
        yield from fetch(f"{DETAIL_API}?{urlencode(params + [('ajax', 'true')])}")
        print(f"Fetched details for {min(offset + 10, len(ids))}/{len(ids)} products")


def materials(product):
    composition = (product.get("detail") or {}).get("detailedComposition") or {}
    return "; ".join(
        f"{part['description']}: "
        + ", ".join(f"{item['percentage']} {item['material']}" for item in part["components"])
        for part in composition.get("parts", [])
        if part.get("components")
    )


def looks(product):
    seo = product.get("seo") or {}
    category = " / ".join(filter(None, [
        product.get("familyName"), product.get("subfamilyName"),
    ]))
    composition = materials(product)
    for color in (product.get("detail") or {}).get("colors", []):
        product_id = color.get("productId", product["id"])
        product_url = (
            f"https://www.zara.com/us/en/{seo.get('keyword')}-p{seo.get('seoProductId')}.html"
            f"?v1={product_id}"
        )
        for image in color.get("xmedia", []):
            info = image.get("extraInfo") or {}
            if image.get("type") != "image" or not info.get("originalName", "").startswith("a"):
                continue
            yield {
                "image_url": info["deliveryUrl"],
                "product_id": product_id,
                "source": "zara",
                "product_name": product.get("name", ""),
                "price": color.get("price", 0) / 100,
                "currency": "USD",
                "category": category,
                "gender": product.get("sectionName", "").lower(),
                "color": color.get("name", ""),
                "description": product.get("description", ""),
                "materials": composition,
                "product_url": product_url,
            }


def main():
    rows = {row["image_url"]: row for product in products() for row in looks(product)}
    with open(OUTPUT, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows.values())
    print(f"Wrote {len(rows)} images to {OUTPUT}")


if __name__ == "__main__":
    main()
