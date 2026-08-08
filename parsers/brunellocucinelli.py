import argparse
import csv
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from schema import CSV_COLUMNS, format_gender, format_price


API = (
    "https://ydsnap3m.api.commercecloud.salesforce.com/search/shopper-search/"
    "v1/organizations/f_ecom_abcp_prd/product-search"
)
OUTPUT = "brunellocucinelli.csv"
LOOK_VIEWS = {"E", "K"}  # Full-body model shots; other views are crops or product-only.


def products(token):
    offset = 0
    while True:
        query = urlencode({
            "siteId": "bc-us",
            "refine": "price=(1..)",
            "currency": "USD",
            "locale": "en-US",
            "expand": "images",
            "offset": offset,
            "limit": 100,
        })
        request = Request(
            f"{API}?{query}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urlopen(request, timeout=30) as response:
            page = json.load(response)

        hits = page.get("hits", [])
        yield from hits
        offset += len(hits)
        print(f"Fetched {offset}/{page['total']} products", file=sys.stderr)
        if not hits or offset >= page["total"]:
            return


def looks(product):
    analytics = product.get("c_analytics") or {}
    category = analytics.get("categoryPath", "")
    if "/ready_to_wear/" not in category:
        return

    price = product.get("c_price") or {}
    color = analytics.get("color") or {}
    for image in (product.get("c_images") or {}).get("large") or []:
        if image.get("imageViewType") in LOOK_VIEWS:
            yield {
                "image_url": image.get("link") or image["url"],
                "product_id": product["productId"],
                "source": "brunellocucinelli",
                "product_name": product.get("productName", ""),
                "price": format_price((price.get("price") or {}).get("value")),
                "currency": price.get("currency", ""),
                "category": category,
                "gender": format_gender(analytics.get("gender", "")),
                "color": color.get("label", ""),
                "description": product.get("c_ariaLabel", ""),
                "product_url": product.get("c_productUrl", ""),
            }


def main():
    parser = argparse.ArgumentParser(description="Export Brunello Cucinelli looks")
    parser.add_argument("--token", required=True, help="Salesforce API bearer token")
    token = parser.parse_args().token

    rows = [row for product in products(token) for row in looks(product)]
    with open(OUTPUT, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} images to {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError) as error:
        sys.exit(f"Request failed: {error}")
