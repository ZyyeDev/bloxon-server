import joblib
import os
import subprocess
from aiohttp import web
import pathlib
import json

print("booting moderation server")

current_dir = pathlib.Path(__file__).parent.resolve()
model_file = current_dir / "model.pkl"
vectorized_file = current_dir / "model_vectorizer.pkl"

if not model_file.exists() or not vectorized_file.exists():
    print("training cuz we dont find ai")
    subprocess.run(["python3", str(current_dir / "train.py")], check=True)

print("== Loading Models ==")
loaded_model = joblib.load(model_file)
vectorizer = joblib.load(vectorized_file)

API_KEY = ""

labels = ['sexual', 'hate', 'violence', 'harassment', 'self-harm', 'sexual/minors', 'hate/threatening', 'violence/graphic']

async def moderationRun(request):
    global loaded_model, vectorizer

    try:
        request_json = await request.json()
    except:
        return web.json_response({'error': 'Invalid request. JSON expected.'}, status=400)

    if 'text' not in request_json:
        return web.json_response({'error': 'Invalid request. JSON with "text" field is expected.'}, status=400)

    if 'API' in request_json:
        if request_json.get("API") != API_KEY:
            pass # no api key for now, i dont really care tbh

    text = request_json['text']

    try:
        new_data_vectorized = vectorizer.transform([text])
        probabilities = loaded_model.predict_proba(new_data_vectorized)

        #print(f"Input text: {text}")
        #print(f"Probabilities type: {type(probabilities)}")
        #print(f"Probabilities length: {len(probabilities)}")

        data = {}
        for i, label in enumerate(labels):
            if len(probabilities[i][0]) > 1:
                data[label] = float(probabilities[i][0][1])
            else:
                data[label] = float(probabilities[i][0][0])
            print(f"{label}: {data[label]}")

        return web.json_response(data, status=200)

    except Exception as e:
        print(f"Error during moderation: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({'error': 'Internal error during moderation'}, status=500)

def initModeration(webApp):
    webApp.add_routes([
        web.post("/moderation/run", moderationRun),
    ])
