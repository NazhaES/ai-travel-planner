import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from langchain_groq import ChatGroq

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# API keys
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
AVIATION_STACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY") or os.getenv("AVIATION_STACK_API_KEY", "")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

# Postgres
DATABASE_URL = "postgresql://{user}:{password}@{host}:{port}/{db}".format(
    user=quote_plus(os.getenv("POSTGRES_USER", "")),
    password=quote_plus(os.getenv("POSTGRES_PASSWORD", "")),
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=os.getenv("POSTGRES_PORT", "5432"),
    db=os.getenv("POSTGRES_DB", ""),
)


def get_llm():
    return ChatGroq(model="openai/gpt-oss-20b")
