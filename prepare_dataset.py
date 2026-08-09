import csv
import hashlib
import os
from collections import defaultdict
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi
ROOT = Path(__file__).resolve().parent
SOURCES = (
    "nike.csv",
    "zara.csv",
    "philippplein.csv",
    "brunellocucinelli.csv",
)
LABELS = "labels.csv"
REQUIRED_COLUMNS = {"image_url", "product_id", "source"}

def read_csv(path, **kwargs):
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, **kwargs)
        return reader.fieldnames, list(reader)

def take_groups(groups, available, target):
    selected = []
    count = 0
    for key in available:
        size = len(groups[key])
        if size <= target - count:
            selected.append(key)
            count += size
        if count == target:
            break
    chosen = set(selected)
    available[:] = [key for key in available if key not in chosen]
    return selected

def main():
    required = [ROOT / name for name in (*SOURCES, LABELS)]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing required files: {', '.join(missing)}")
    token = os.environ["HF_TOKEN"]

    rows = []
    columns = None
    for name in SOURCES:
        fieldnames, source_rows = read_csv(ROOT / name)
        if not fieldnames or not REQUIRED_COLUMNS <= set(fieldnames):
            raise ValueError(f"{name} is missing required columns")
        if columns is not None and fieldnames != columns:
            raise ValueError(f"{name} has a different schema")
        columns = fieldnames
        rows.extend(source_rows)

    label_columns, label_rows = read_csv(ROOT / LABELS, skipinitialspace=True)
    if not label_columns or not {"id", "label"} <= set(label_columns):
        raise ValueError(f"{LABELS} must contain id and label columns")
    labels = {}
    for row in label_rows:
        if row["id"] in labels:
            raise ValueError(f"duplicate label id: {row['id']}")
        labels[row["id"]] = row["label"]

    groups = defaultdict(list)
    seen_ids = set()
    for row in rows:
        if not all(row.get(column) for column in REQUIRED_COLUMNS):
            raise ValueError("source row has an empty image_url, product_id, or source")
        image_id = hashlib.sha256(row["image_url"].encode()).hexdigest()
        if image_id in seen_ids:
            raise ValueError(f"duplicate image: {row['image_url']}")
        seen_ids.add(image_id)
        row["id"] = image_id
        row["label"] = labels.get(image_id, "")
        groups[(row["source"], row["product_id"])].append(row)

    order = sorted(groups, key=lambda key: hashlib.sha256("\0".join(key).encode()).digest())
    test = take_groups(groups, order, 200)
    val = take_groups(groups, order, 500)
    splits = {"test": test, "val": val, "train": order}
    fields = ["id", "label", *columns]
    outputs = []
    for split, keys in splits.items():
        split_rows = [row for key in keys for row in groups[key]]
        output = ROOT / f"dataset_{split}.csv"
        with output.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(split_rows)
        outputs.append(output)
        print(f"{split}: {len(split_rows)} images")

    api = HfApi(token=token)
    repo_id = f"{api.whoami()['name']}/oldmoney"
    api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)
    operations = [CommitOperationAdd(path_in_repo=path.name, path_or_fileobj=path) for path in outputs]
    api.create_commit(repo_id, repo_type="dataset", operations=operations, commit_message="Upload prepared dataset")
    print(f"uploaded splits to {repo_id}")
if __name__ == "__main__":
    main()
