import json
import requests
url = "https://jsonplaceholder.typicode.com/todos/1"
resp = requests.get("https://jsonplaceholder.typicode.com/todos/1")
resp.raise_for_status
data=resp.json()
print("Gelen veri (python dict):", data)

with open("todo.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

with open("todo.json", "r", encoding="utf-8") as f:
    loaded = json.load(f)
print("Dosyadan okunan:", loaded)

print("title:", loaded["title"])



