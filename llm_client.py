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

@dataclass
class LLMResponse:
    """Data class to hold the response from the LLM."""
    thinking: str  # The model's reasoning process
    content: str   # The actual response content
    model: ModelType
    tokens_used: int
    provider: ProviderType

class LLMClient:
    """Client for interacting with various Language Learning Models."""
    
    # System prompts for different response types
    SYSTEM_PROMPT = """You are a helpful AI assistant. For each response, you must:
1. First, explain your thinking process in a section marked with [THINKING]
2. Then, provide your actual response in a section marked with [CONTENT]

Example format:
[THINKING]
Here I explain how I'm approaching the task...
[CONTENT]
Here is my actual response...

Always use these exact markers and maintain this structure."""

    def __init__(self, config_path: Optional[str] = None, 
                 provider: Optional[ProviderType] = None,
                 model: Optional[ModelType] = None,
                 api_key: Optional[str] = None):
        """
        Initialize the LLM client.
        
        Args:
            config_path: Path to the config file
            provider: Provider to use (overrides config default)
            model: Model to use (overrides config default)
            api_key: API key (overrides config)
        """
        self.config = self.load_config(config_path)
        self.provider = provider or self.config.get('default_provider', 'openai')
        self.model = model or self.config.get('default_model', 'gpt-o3')
        
        # Validate provider and model
        if self.provider not in self.config:
            raise ConfigurationError(f"Provider {self.provider} not configured")
        
        provider_config = self.config[self.provider]
        if 'models' not in provider_config or self.model not in provider_config['models']:
            raise UnsupportedModelError(f"Model {self.model} not supported by provider {self.provider}")
        
        # Set API key and initialize client
        self.api_key = api_key or provider_config['api_key']
        if not self.api_key:
            raise ConfigurationError(f"No API key provided for {self.provider}")
        
        self._init_client()
        
    @staticmethod
    def load_config(config_path: Optional[str] = None) -> dict:
        """Load configuration from YAML file."""
        config_path = config_path or "config.yaml"
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            return config
        except FileNotFoundError:
            template_path = Path("config.template.yaml")
            if template_path.exists():
                raise ConfigurationError(
                    "Configuration file not found. Please copy config.template.yaml "
                    "to config.yaml and fill in your API keys"
                )
            raise ConfigurationError("Configuration file not found")
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Error parsing configuration file: {str(e)}")

    def _init_client(self):
        """Initialize the appropriate client based on provider."""
        if self.provider == "openai":
            self.client = OpenAI(api_key=self.api_key)
        elif self.provider == "anthropic":
            from anthropic import Anthropic
            self.client = Anthropic(api_key=self.api_key)
        elif self.provider == "together":
            import together
            together.api_key = self.api_key
            self.client = together
        elif self.provider == "xai":
            from xai import Client as XAIClient
            self.client = XAIClient(api_key=self.api_key)
        else:
            raise UnsupportedModelError(f"Provider {self.provider} not supported")

    def get_response(self, prompt: str) -> LLMResponse:
        """
        Get a response from the LLM for the given prompt.
        
        Args:
            prompt: The prompt to send to the model
            
        Returns:
            LLMResponse object containing the response
        """
        try:
            if self.provider == "openai":
                return self._get_openai_response(prompt)
            elif self.provider == "anthropic":
                return self._get_anthropic_response(prompt)
            elif self.provider == "together":
                return self._get_together_response(prompt)
            elif self.provider == "xai":
                return self._get_xai_response(prompt)
            else:
                raise UnsupportedModelError(f"Provider {self.provider} not supported")
        except Exception as e:
            raise Exception(f"Error getting response from {self.provider}/{self.model}: {str(e)}")

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

    def _get_openai_response(self, prompt: str) -> LLMResponse:
        """Handle OpenAI API calls."""
        response = self.client.chat.completions.create(
            model=self.config[self.provider]['models'][self.model],
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        response_text = response.choices[0].message.content
        thinking, content = self._parse_response(response_text)
        
        return LLMResponse(
            thinking=thinking,
            content=content,
            model=self.model,
            tokens_used=response.usage.total_tokens,
            provider=self.provider
        )

    def _get_anthropic_response(self, prompt: str) -> LLMResponse:
        """Handle Anthropic API calls."""
        from anthropic import Anthropic
        response = self.client.messages.create(
            model=self.config[self.provider]['models'][self.model],
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        response_text = response.content[0].text
        thinking, content = self._parse_response(response_text)
        
        return LLMResponse(
            thinking=thinking,
            content=content,
            model=self.model,
            tokens_used=response.usage.input_tokens + response.usage.output_tokens,
            provider=self.provider
        )

    def _get_together_response(self, prompt: str) -> LLMResponse:
        """Handle Together.ai API calls."""
        import together
        full_prompt = f"{self.SYSTEM_PROMPT}\n\nUser: {prompt}\nAssistant:"
        response = self.client.complete(
            prompt=full_prompt,
            model=self.config[self.provider]['models'][self.model],
            temperature=0.7,
            max_tokens=1000
        )
        
        response_text = response['output']['choices'][0]['text']
        thinking, content = self._parse_response(response_text)
        
        return LLMResponse(
            thinking=thinking,
            content=content,
            model=self.model,
            tokens_used=response['output']['usage']['total_tokens'],
            provider=self.provider
        )

    def _get_xai_response(self, prompt: str) -> LLMResponse:
        """Handle xAI (Grok) API calls."""
        from xai import Client as XAIClient
        response = self.client.chat.completions.create(
            model=self.config[self.provider]['models'][self.model],
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        response_text = response.choices[0].message.content
        thinking, content = self._parse_response(response_text)
        
        return LLMResponse(
            thinking=thinking,
            content=content,
            model=self.model,
            tokens_used=response.usage.total_tokens,
            provider=self.provider
        )