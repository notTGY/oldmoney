import argparse, base64, csv, json, sys, time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://ydsnap3m.api.commercecloud.salesforce.com/search/shopper-search/v1/organizations/f_ecom_abcp_prd/product-search"
FIELDS = [
    "image_url", "product_id", "represented_product_id", "source",
    "image_view_type", "product_name", "description", "details", "price",
    "currency", "category", "gender", "color", "season", "product_url",
]

def fetch(offset, limit, token, retries=3):
    params = {
        "siteId": "bc-us", "refine": "price=(1..)", "sort": "best-matches",
        "currency": "USD", "locale": "en-US", "expand": "images",
        "offset": offset, "limit": limit,
    }
    headers = {
        "Accept": "application/json",
        "Referer": "https://shop.brunellocucinelli.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{API}?{urlencode(params)}", headers=headers)
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
        except URLError:
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt)

def rows(hit, views):
    analytics = hit.get("c_analytics") or {}
    category = analytics.get("categoryPath", "")
    if "/ready_to_wear/" not in category:
        return
    price = (hit.get("c_price") or {}).get("price") or {}
    color = analytics.get("color") or {}
    represented = hit.get("representedProduct") or {}
    for image in (hit.get("c_images") or {}).get("large") or []:
        if image.get("imageViewType") not in views:
            continue
        yield {
            "image_url": image.get("link") or image.get("url", ""),
            "product_id": hit.get("productId", ""),
            "represented_product_id": represented.get("id", ""),
            "source": "brunellocucinelli",
            "image_view_type": image.get("imageViewType", ""),
            "product_name": hit.get("productName", ""),
            "description": hit.get("c_shortDescription", ""),
            "details": hit.get("c_ariaLabel", ""),
            "price": price.get("value", ""),
            "currency": (hit.get("c_price") or {}).get("currency", ""),
            "category": category,
            "gender": analytics.get("gender", ""),
            "color": color.get("label", ""),
            "season": analytics.get("season", ""),
            "product_url": hit.get("c_productUrl", ""),
        }

def main():
    parser = argparse.ArgumentParser(description="Export Brunello Cucinelli look images")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--views", default="E,K", help="comma-separated image view types")
    parser.add_argument("--token", required=True, help="Storefront API bearer token")
    args = parser.parse_args()
    if json.loads(base64.urlsafe_b64decode(args.token.split(".")[1] + "==")).get("exp", 0) <= time.time():
        raise URLError("bearer token has expired")
    views, offset, products, images = set(args.views.split(",")), 0, 0, 0
    with open("brunellocucinelli.csv", "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        while True:
            page = fetch(offset, args.limit, args.token)
            hits = page.get("hits") or []
            for hit in hits:
                products += 1
                for row in rows(hit, views):
                    writer.writerow(row)
                    images += 1
            offset += len(hits)
            print(f"Fetched {offset}/{page.get('total', '?')} products", file=sys.stderr)
            if not hits or offset >= page.get("total", offset):
                break
    print(f"Wrote {images} images from {products} products to brunellocucinelli.csv")

if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError) as error:
        sys.exit(f"Request failed: {error}. Check that --token is current and valid.")
