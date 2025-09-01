import json

with open("links.json", "r", encoding="utf-8") as f:
    links = json.load(f)

for k, v in links.items():
    print(f"\nLien ID: {k}")
    for field, value in v.items():
        print(f"  {field}: {value}")
