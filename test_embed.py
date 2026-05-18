import httpx
import os
import litellm

litellm.client_session = httpx.Client(verify=False)

# 1. Set your API Key (You can also set this as OPENAI_API_KEY environment variable)
qgenie_api_key = os.environ.get("QGENIE_API_KEY", "<your-qgenie-api-key-here>")

# 2. Call LiteLLM's embedding function
response = litellm.embedding(
        model="openai/stella_en_400M_v5",       # The 'openai/' prefix tells LiteLLM to use OpenAI's API format
#        model="openai/qcom_embedd",
                input=["How do I use embeddings with LiteLLM?"],
                    api_base="https://qpilot-api.qualcomm.com/v1",
                        api_key=qgenie_api_key
                        )

# 3. Extract your embeddings
print(response)
