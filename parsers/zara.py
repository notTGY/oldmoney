import csv
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API = "https://www.zara.com/us/en/category/2443335/products?ajax=true"
OUTPUT = "zara.csv"
HEADERS = {
    "Referer": "https://www.zara.com/us/en/man-all-products-l7465.html?v1=2443335",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
}
COLUMNS = [
    "image_url",
    "product_id",
    "source",
    "product_name",
    "price",
    "currency",
    "category",
    "gender",
    "color",
    "description",
    "product_url",
]


def products(catalog):
    for group in catalog["productGroups"]:
        for element in group["elements"]:
            yield from element.get("commercialComponents", [])


def looks(product):
    if product.get("kind") != "Wear":
        return

    seo = product.get("seo") or {}
    category = " / ".join(filter(None, [
        product.get("familyName"),
        product.get("subfamilyName"),
    ]))
    product_url = (
        f"https://www.zara.com/us/en/{seo.get('keyword')}-p{seo.get('seoProductId')}.html"
        f"?v1={product['id']}"
    )
    for color in (product.get("detail") or {}).get("colors", []):
        for image in color.get("xmedia", []):
            original_name = (image.get("extraInfo") or {}).get("originalName", "")
            if image.get("type") != "image" or not original_name.startswith("a"):
                continue
            yield {
                "image_url": image["extraInfo"]["deliveryUrl"],
                "product_id": product["id"],
                "source": "zara",
                "product_name": product.get("name", ""),
                "price": color.get("price", product.get("price", 0)) / 100,
                "currency": "USD",
                "category": category,
                "gender": product.get("sectionName", "").lower(),
                "color": color.get("name", ""),
                "description": product.get("description", ""),
                "product_url": product_url,
            }


def main():
    with urlopen(Request(API, headers=HEADERS), timeout=60) as response:
        catalog = json.load(response)

    rows = {
        row["image_url"]: row
        for product in products(catalog)
        for row in looks(product)
    }
    with open(OUTPUT, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows.values())
    print(f"Wrote {len(rows)} images to {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError) as error:
        sys.exit(f"Request failed: {error}")
