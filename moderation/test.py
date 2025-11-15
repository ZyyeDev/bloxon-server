import requests
import time

session = requests.Session()
session.headers.update({
    'x-api-key': '',
    'Content-Type': 'application/json'
})

labels = ['sexual', 'hate', 'violence', 'harassment', 'self-harm', 'sexual/minors', 'hate/threatening', 'violence/graphic']
url = "http://46.224.26.214:8080/moderation"

def post_text(text, timeout=2, retries=3, backoff=0.5):
    for attempt in range(1, retries + 1):
        try:
            resp = session.post(url, json={'text': text}, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == retries:
                raise
            time.sleep(backoff * (2 ** (attempt - 1)))
    raise RuntimeError("unreachable")

try:
    while True:
        text = input("Input: ")
        if not text:
            continue
        try:
            data = post_text(text)
        except Exception as e:
            print("Request error:", e)
            continue

        print(data)

        #print("Predictions:")
        #for label in labels:
        #    print(f"{label}: {data.get(label, 0.0):.2f}")
except KeyboardInterrupt:
    print("\nExiting.")
