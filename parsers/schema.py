CSV_COLUMNS = [
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
    "materials",
    "product_url",
]


def format_price(value):
    return "" if value in (None, "") else f"{float(value):.2f}"


def format_gender(values):
    if isinstance(values, str):
        values = [values]
    aliases = {"male": "men", "female": "women", "man": "men", "woman": "women"}
    normalized = {aliases.get(value.lower(), value.lower()) for value in values if value}
    return "|".join(sorted(normalized))
