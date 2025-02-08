def transform_chat_to_context(messages: list[dict]) -> str:
    """
    Transform chat messages into a summary text format for LLM context.
    Each message should contain 'text' and 'from' fields.
    'from' should have an 'is_bot' field to determine if message is from user or bot.
    
    Args:
        messages: List of chat message dictionaries
        
    Returns:
        Formatted string containing the chat context
    """
    context_parts = []
    
    for msg in messages:
        speaker = "Assistant" if msg['from'].get('is_bot', False) else "Human"
        text = msg['text'].strip()
        context_parts.append(f"{speaker}: {text}")
        
    return "\n".join(context_parts)
