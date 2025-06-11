import os
import json
import uuid
from typing import Optional, Literal, Dict, Any, Tuple
from dataclasses import dataclass
import yaml
from pathlib import Path
from database import save_prompt_history

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
    request_id: str  # Unique identifier for this request
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
        # Generate a unique request ID
        request_id = str(uuid.uuid4())
        print(f"\n🔍 Request ID: {request_id}")
        
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
            
            try:
                # Try to parse as JSON
                response_json = json.loads(full_response)
                thinking = response_json.get("thinking", "")
                content = response_json.get("content", {})
                
                # For negotiation responses, validate content
                if isinstance(content, dict) and "opinion" in content:
                    content = {"opinion": content.get("opinion")}

                if isinstance(content, dict) and "action" in content:
                    if content["action"] not in ["Offer", "Refuse", "Kill"]:
                        print(f"\n⚠️ Invalid action type in response: {content['action']}")
                        content = {
                            "action": "Refuse",
                            "damage": None,
                            "target": None,
                            "speech": "I need more time to think about this."
                        }
                    elif content["action"] == "Offer" and not isinstance(content.get("damage"), (int, float)):
                        print(f"\n⚠️ Invalid damage amount for Offer action: {content.get('damage')}")
                        content = {
                            "action": "Refuse",
                            "damage": None,
                            "target": None,
                            "speech": "I need more time to think about this."
                        }
                    elif content["action"] == "Kill" and not isinstance(content.get("target"), str):
                        print(f"\n⚠️ Invalid target for Kill action: {content.get('target')}")
                        content = {
                            "action": "Refuse",
                            "damage": None,
                            "target": None,
                            "speech": "I need more time to think about this."
                        }
                
                # Save prompt and response to database with request ID
                save_prompt_history(
                    raw_prompt=prompt,
                    raw_response=full_response,
                    request_id=request_id
                )
                
                return LLMResponse(thinking=thinking, content=content, request_id=request_id)
                
            except json.JSONDecodeError as e:
                print(f"\n⚠️ Failed to parse response as JSON: {str(e)}")
                print("Raw response:", full_response)
                
                # Save failed response to database
                save_prompt_history(
                    raw_prompt=prompt,
                    raw_response=full_response,
                    request_id=request_id
                )
                
                # Return a default response
                return LLMResponse(
                    thinking="Failed to parse response",
                    content={
                        "action": "Refuse",
                        "damage": None,
                        "target": None,
                        "speech": "I need more time to think about this."
                    },
                    request_id=request_id
                )
            
        except Exception as e:
            # Save failed prompt to database with error message
            save_prompt_history(
                raw_prompt=prompt,
                raw_response=f"ERROR: {str(e)}",
                request_id=request_id
            )
            raise LLMError(f"Error getting response from LLM: {str(e)}")

    def _parse_response(self, text: str) -> Tuple[str, Dict]:
        """
        Parse the response text into thinking and content parts.
        Returns a tuple of (thinking, content) where content is a dictionary.
        """
        try:
            # Try to parse as JSON
            response_json = json.loads(text)
            
            # Validate response structure
            if not isinstance(response_json, dict):
                raise ValueError("Response is not a dictionary")
            
            # Extract thinking and content
            thinking = response_json.get("thinking", "")
            content = response_json.get("content", {})
            
            # For negotiation responses, ensure content has required fields
            if isinstance(content, dict) and "action" in content:
                if content["action"] not in ["Offer", "Refuse", "Kill"]:
                    raise ValueError(f"Invalid action type: {content['action']}")
                    
                # Validate damage amount for Offer action
                if content["action"] == "Offer":
                    damage = content.get("damage")
                    if not isinstance(damage, (int, float)):
                        raise ValueError(f"Invalid damage amount for Offer action: {damage}")
                
                # Validate target for Kill action
                if content["action"] == "Kill":
                    target = content.get("target")
                    if not isinstance(target, str):
                        raise ValueError(f"Invalid target for Kill action: {target}")
                
                # Ensure speech is present
                if "speech" not in content:
                    content["speech"] = ""
            
            return thinking, content
            
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse JSON response: {str(e)}")
            print("Raw response:", text)
            
            # Create a properly formatted response
            thinking = "Failed to parse response"
            content = {
                "action": "Refuse",
                "damage": None,
                "target": None,
                "speech": "I need more time to think about this."
            }
            
            return thinking, content
        except ValueError as e:
            print(f"Warning: Invalid response format: {str(e)}")
            print("Raw response:", text)
            
            # Create a properly formatted response
            thinking = f"Invalid response format: {str(e)}"
            content = {
                "action": "Refuse",
                "damage": None,
                "target": None,
                "speech": "I need more time to think about this."
            }
            
            return thinking, content