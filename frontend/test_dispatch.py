import requests
res = requests.post("http://localhost:8000/api/v1/dispatch/", json={"date": "2026-04-09", "total_trucks": 6})
print(res.status_code)
print(res.json())
