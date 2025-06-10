import os
from typing import Optional, Literal, Dict, Any
from dataclasses import dataclass
import yaml
from pathlib import Path

# Provider-specific imports
from openai import OpenAI

ProviderType = Literal["openai", "anthropic", "together", "xai"]
ModelType = Literal[
    # OpenAI models
    "gpt-o1", "gpt-o3", "gpt-o4-mini",
    # Claude models
    "claude-s3", "claude-s4", "claude-o4",
    # Deepseek models
    "deepseek-r1",
    # Grok models
    "grok-3"
]

class UnsupportedModelError(Exception):
    """Exception raised when an unsupported model is specified."""
    pass

class ConfigurationError(Exception):
    """Exception raised when there are configuration issues."""
    pass

class LLMError(Exception):
    """Exception raised when there are errors in LLM operations."""
    pass

@dataclass
class LLMResponse:
    """Data class to hold the response from the LLM."""
    thinking: str  # The model's reasoning process
    content: str   # The actual response content
    model: Optional[str] = None
    tokens_used: Optional[int] = None
    provider: Optional[str] = None

class LLMClient:
    """Client for interacting with various Language Learning Models."""
    
    def __init__(self, model: str = "gpt-3.5-turbo", api_key: Optional[str] = None):
        """Initialize the LLM client."""
        self.model = model
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError("OpenAI API key not provided and not found in environment variables")
        
        # Load system prompt
        prompts_dir = Path(__file__).parent / "prompts"
        try:
            with open(prompts_dir / "system.txt", 'r') as f:
                self._system_prompt = f.read()
        except FileNotFoundError:
            raise RuntimeError("Could not find system prompt template")
        
        # Initialize OpenAI client
        self._client = OpenAI(api_key=self._api_key)
    
    def get_response(self, prompt: str) -> LLMResponse:
        """Get a response from the LLM."""
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Extract thinking and content from response
            full_response = response.choices[0].message.content
            thinking, content = self._parse_response(full_response)
            
            return LLMResponse(thinking=thinking, content=content)
            
        except Exception as e:
            raise LLMError(f"Error getting response from LLM: {str(e)}")

    def _parse_response(self, text: str) -> tuple[str, str]:
        """Parse the response text into thinking and content parts."""
        thinking = ""
        content = ""
        
        # Split the text into sections
        parts = text.split("[THINKING]")
        if len(parts) > 1:
            thinking_and_content = parts[1].split("[CONTENT]")
            if len(thinking_and_content) > 1:
                thinking = thinking_and_content[0].strip()
                content = thinking_and_content[1].strip()
            else:
                # If no [CONTENT] marker, treat everything after [THINKING] as thinking
                thinking = thinking_and_content[0].strip()
        else:
            # If no markers found, treat entire response as content
            content = text.strip()
            
        return thinking, content