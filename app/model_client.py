import os
import requests
import logging
from google.adk.models.lite_llm import LiteLlm

logger = logging.getLogger(__name__)

def is_ollama_available(url: str = "http://localhost:11434", timeout: float = 1.0) -> bool:
    """Check if the local Ollama service is running and responsive."""
    try:
        response = requests.get(f"{url}/api/tags", timeout=timeout)
        return response.status_code == 200
    except requests.RequestException:
        return False

def get_model_client() -> LiteLlm:
    """
    Get the appropriate model client.
    Tries to use local Ollama with Gemma4:25b first.
    Falls back to Gemini 3.5 Flash (via LiteLLM gemini/gemini-2.5-flash) if Ollama is unavailable.
    """
    # Allow overriding via environment variables
    force_local = os.getenv("FORCE_LOCAL_LLM", "").lower() == "true"
    force_cloud = os.getenv("FORCE_CLOUD_LLM", "").lower() == "true"
    
    ollama_url = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "gemma4:25b")
    
    # We use gemini-2.5-flash as the standard Gemini Flash model in LiteLLM
    gemini_model = os.getenv("GEMINI_MODEL", "gemini/gemini-2.5-flash")
    
    if not force_cloud and (force_local or is_ollama_available(ollama_url)):
        logger.info(f"Using local Ollama model '{ollama_model}' at {ollama_url}")
        # LiteLLM expects 'ollama_chat/model_name' for chat completion
        return LiteLlm(
            model=f"ollama_chat/{ollama_model}",
            api_base=ollama_url
        )
    else:
        logger.info(f"Ollama local service not available or cloud forced. Falling back to Gemini: '{gemini_model}'")
        # Ensure GEMINI_API_KEY is present if running in cloud mode
        if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
            logger.warning("Neither GEMINI_API_KEY nor GOOGLE_API_KEY is set. Gemini calls may fail.")
        
        return LiteLlm(
            model=gemini_model
        )
