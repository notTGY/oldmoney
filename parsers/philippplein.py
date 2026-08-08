import csv
from http.cookiejar import CookieJar
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import build_opener, HTTPCookieProcessor, Request
from schema import CSV_COLUMNS, format_gender, format_price


API = (
    "https://www.plein.com/ge/men/?pmin=1.00&prefn1=hasPicture&prefv1=true"
    "&start=0&sz=12&format=page-element"
)
OUTPUT = "philippplein.csv"
HEADERS = {
    "Accept": "text/html, */*; q=0.01",
    "Referer": "https://www.plein.com/ge/men/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}


class ProductPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.products = []
        self.product = None
        self.depth = 0
        self.next_url = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        classes = set(attrs.get("class", "").split())
        if tag == "div" and "infinite-scroll-placeholder" in classes:
            self.next_url = attrs.get("data-grid-url")
        if tag == "div" and "b-product_tile" in classes:
            self.product, self.depth = {}, 1
            return
        if self.product is None:
            return
        if tag == "div":
            self.depth += 1
        elif tag == "a" and "js-product_link" in classes:
            self.product.update({
                "product_id": attrs["data-id"],
                "product_name": attrs["data-name"],
                "price": format_price(attrs["data-price"]),
                "currency": attrs["data-currency"],
                "category": attrs["data-category"],
                "color": attrs["data-variant"],
                "product_url": urljoin("https://www.plein.com", attrs["href"]),
            })
        elif (
            tag == "img"
            and "js-outfit-view" in classes
            and "/images/outfit/" in attrs.get("data-src", "")
        ):
            self.product["image_url"] = attrs["data-src"].partition("?")[0]

    def handle_endtag(self, tag):
        if self.product is None or tag != "div":
            return
        self.depth -= 1
        if self.depth == 0:
            if "image_url" in self.product:
                self.product.update(source="philippplein", gender=format_gender("man"))
                self.products.append(self.product)
            self.product = None


def main():
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    rows, seen, url = {}, set(), API
    while url and url not in seen:
        seen.add(url)
        with opener.open(Request(url, headers=HEADERS), timeout=60) as response:
            page = ProductPage()
            page.feed(response.read().decode())
        rows.update((product["image_url"], product) for product in page.products)
        print(f"Fetched {len(rows)} products")
        url = page.next_url

    with open(OUTPUT, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows.values())
    print(f"Wrote {len(rows)} images to {OUTPUT}")


if __name__ == "__main__":
    main()
