import os
from pathlib import Path

import pandas as pd
import requests

BASE_URL = os.getenv("SEHATI_API_BASE_URL", "https://fastapi-uks-production.up.railway.app").rstrip("/")
TOKEN = os.getenv("SEHATI_API_TOKEN", "")
IMPORT_FILE = Path(os.getenv("SEHATI_MEDICINE_IMPORT_FILE", "data/imports/medicine_inventory_export.csv"))

if not TOKEN:
    raise RuntimeError("Set SEHATI_API_TOKEN before running this import script.")
if not IMPORT_FILE.is_file():
    raise FileNotFoundError(f"Medicine import file not found: {IMPORT_FILE}")

df = pd.read_csv(IMPORT_FILE)

for _, row in df.iterrows():

    payload = {
        "name": row["name"],
        "unit": row["unit"],
        "stock": int(row["stock"]),
        "minimum_stock": int(row["minimum_stock"])
    }

    res = requests.post(

        f"{BASE_URL}/api/medicines",

        json=payload,

        headers={
            "Authorization":
            f"Bearer {TOKEN}"
        }

    )

    print(
        row["name"],
        res.status_code
    )
