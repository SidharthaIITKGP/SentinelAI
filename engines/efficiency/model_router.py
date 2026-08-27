from api.schemas import ModelConfig, RiskLevel, UseCase
import litellm

def route_model(risk_level: str, use_case: str) -> ModelConfig:
    """
    Given risk level + use case -> pick the right LLM model and token budget.
    """
    # Normalize inputs for comparison if they are enums
    r_level = risk_level.value if hasattr(risk_level, "value") else risk_level
    u_case = use_case.value if hasattr(use_case, "value") else use_case

    if r_level == "LOW" and u_case == "hr_copilot":
        return ModelConfig(
            model="gpt-4o-mini",
            max_tokens=500,
            temperature=0.3,
            reason="Fast + cheap"
        )
    elif r_level == "MEDIUM" and u_case == "customer_chatbot":
        return ModelConfig(
            model="gpt-4o",
            max_tokens=800,
            temperature=0.7,
            reason="Quality matters"
        )
    elif r_level == "HIGH" and u_case == "customer_chatbot":
        return ModelConfig(
            model="gpt-4o",
            max_tokens=1000,
            temperature=0.7,
            reason="Full capability"
        )
    elif r_level == "HIGH" and u_case == "finance_tool":
        return ModelConfig(
            model="gpt-4o",
            max_tokens=1000,
            temperature=0.1,
            reason="Regulated, needs best"
        )
    
    # Default fallback
    return ModelConfig(
        model="gpt-4o-mini",
        max_tokens=500,
        temperature=0.3,
        reason="Default"
    )

async def execute_model(prompt: str, config: ModelConfig) -> dict:
    """
    Executes the LLM call using litellm.acompletion based on the ModelConfig.
    Returns a dict with response string and token usage.
    """
    # Note: litellm requires the OPENAI_API_KEY environment variable to be set for gpt models
    response = await litellm.acompletion(
        model=config.model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=config.max_tokens,
        temperature=config.temperature
    )
    
    return {
        "response": response.choices[0].message.content,
        "tokens_input": response.usage.prompt_tokens,
        "tokens_output": response.usage.completion_tokens,
        "tokens_total": response.usage.total_tokens,
        "model": config.model
    }
