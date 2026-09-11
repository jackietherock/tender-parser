from google import genai
from dotenv import load_dotenv

import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

print("Зчитуємо список доступних моделей...\n")
for m in client.models.list():
    # Перевіряємо, чи підтримує модель генерацію тексту
    if "generateContent" in m.supported_actions:
        # Виводимо назву без префікса "models/"
        model_id = m.name.replace("models/", "")
        print(f"- {model_id}")