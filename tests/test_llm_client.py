from llm_client import LLMClient, LLMResponse, UnsupportedModelError, ConfigurationError

def test_llm_client():
    print("Testing LLMClient initialization and response...")
    
    try:
        # Test client initialization
        client = LLMClient()
        print("✅ Successfully initialized LLMClient")
        
        # Test getting a response
        prompt = "Say 'Hello, World!' in a creative way."
        response = client.get_response(prompt)
        
        print("\nResponse details:")
        print(f"Content: {response.content}")
        print(f"Model used: {response.model}")
        print(f"Tokens used: {response.tokens_used}")
        print("✅ Successfully got response from the model")
        
        # Test model switching
        print("\nTesting model switching...")
        original_model = client.model
        new_model = "gpt-o1" if original_model == "gpt-o3" else "gpt-o3"
        
        client.model = new_model
        client._openai_model = client.MODEL_MAPPING[new_model]
        
        response = client.get_response("Say 'Hello' briefly.")
        print(f"Response from new model ({new_model}): {response.content}")
        print("✅ Successfully switched models")
        
    except UnsupportedModelError as e:
        print(f"❌ Model Error: {str(e)}")
    except ConfigurationError as e:
        print(f"❌ Configuration Error: {str(e)}")
    except Exception as e:
        print(f"❌ Unexpected Error: {str(e)}")

if __name__ == "__main__":
    test_llm_client() 