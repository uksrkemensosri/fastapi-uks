import pandas as pd
import requests

BASE_URL = "https://fastapi-uks-production.up.railway.app"

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwicm9sZSI6ImFkbWluIiwiaWF0IjoxNzgwMjQwNzY3LCJleHAiOjE3ODAyNDQzNjd9.LboTv-DGOnCwjWgVAS7zb657XTQvgKx5HFVrLYwagzM"

df = pd.read_csv(
    "medicine_inventory_export.csv"
)

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