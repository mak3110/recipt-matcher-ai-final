
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv("api.env", override=True)

base_url = os.getenv("http://localhost:20128")
api_key = os.getenv("Sk-79c8e7778d64e89c-448546-7667b953")

print(f"Base URL loaded: {base_url}")
print(f"API Key loaded: {bool(api_key)} (starts with: {api_key[:6] if api_key else 'EMPTY'})")

try:
    client = OpenAI(base_url=base_url, api_key=api_key)

    response = client.chat.completions.create(
        model="auto",  # replace with your actual combo/model name if "auto" doesn't work
        messages=[{"role": "user", "content": "Say hello in one sentence."}]
    )

    print("\n✅ SUCCESS")
    print("Response:", response.choices[0].message.content)
    print("\nFull raw response object:")
    print(response)

except Exception as e:
    print("\n❌ FAILED")
    print(f"Error type: {type(e).__name__}")
    print(f"Error message: {e}")