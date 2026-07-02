import os
import requests
import logging
from typing import Optional
from google.adk.models.lite_llm import LiteLlm

logger = logging.getLogger(__name__)

def get_ollama_matching_model(model_name: str, url: str = "http://localhost:11434", timeout: float = 1.0) -> Optional[str]:
    """
    Check if the local Ollama service is running and has a model matching the requested name.
    Returns the exact installed model name if found, otherwise None.
    """
    try:
        response = requests.get(f"{url}/api/tags", timeout=timeout)
        if response.status_code != 200:
            return None
        data = response.json()
        models = data.get("models", [])
        model_names = [m.get("name") for m in models if m.get("name")]
        
        # 1. Exact match
        if model_name in model_names:
            return model_name
            
        # 2. Base model match (e.g. gemma4:25b matches gemma4:26b)
        base_name = model_name.split(":")[0]
        for name in model_names:
            if name.split(":")[0] == base_name:
                return name
        return None
    except Exception:
        return None

def get_model_client() -> LiteLlm:
    """
    Get the appropriate model client.
    Tries to use local Ollama with Gemma4:25b (or matching installed model like gemma4:26b) first.
    Falls back to Gemini 3.5 Flash (via LiteLLM gemini/gemini-2.5-flash) if Ollama or a matching model is unavailable.
    """
    # Allow overriding via environment variables
    force_local = os.getenv("FORCE_LOCAL_LLM", "").lower() == "true"
    force_cloud = os.getenv("FORCE_CLOUD_LLM", "").lower() == "true"
    
    ollama_url = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "gemma4:25b")
    
    # We use gemini-2.5-flash as the standard Gemini Flash model in LiteLLM
    gemini_model = os.getenv("GEMINI_MODEL", "gemini/gemini-2.5-flash")
    
    matched_model = None if force_cloud else get_ollama_matching_model(ollama_model, ollama_url)
    
    if force_local or matched_model:
        model_to_use = matched_model or ollama_model
        logger.info(f"Using local Ollama model '{model_to_use}' at {ollama_url} with fallback to {gemini_model}")
        # LiteLLM expects 'ollama_chat/model_name' for chat completion
        return LiteLlm(
            model=f"ollama_chat/{model_to_use}",
            api_base=ollama_url,
            fallbacks=[gemini_model]
        )
    else:
        logger.info(f"Ollama local service or matching model not available. Using Gemini: '{gemini_model}'")
        # Ensure GEMINI_API_KEY is present if running in cloud mode
        if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
            logger.warning("Neither GEMINI_API_KEY nor GOOGLE_API_KEY is set. Gemini calls may fail.")
        
        return LiteLlm(
            model=gemini_model
        )
