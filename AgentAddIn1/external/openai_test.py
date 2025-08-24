from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables from .env file in the root directory
load_dotenv()

# Get the OpenAI API key from environment variable
api_key = os.getenv("OPENAI_API_KEY")
print(api_key)
if not api_key:
    raise ValueError("OPENAI_API_KEY not found in environment variables.")

client = OpenAI(api_key=api_key)

# Make a simple API call to check the key
response = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "Say hello!"}]
)

print(response.choices[0].message.content)