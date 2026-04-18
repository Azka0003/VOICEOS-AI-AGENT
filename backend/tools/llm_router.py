import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

def get_llm(temperature=0.1):
    """Returns the primary LLM instance (Groq). Can be expanded to fallback to Ollama."""
    return ChatGroq(
        temperature=temperature,
        model_name=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        api_key=os.getenv("GROQ_API_KEY")
    )