from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# --- Main System Prompt ---
SYSTEM_PROMPT = """
You are a friendly, local AI assistant for Qeshm Island, Iran. Answer in Persian (فارسی).
- Use provided context documents (labeled [source:id]) when relevant.
- If the context doesn't contain the answer, say you don't know and offer to search the web.
- Prefer descriptive and helpful answers (3-6 sentences) and finish with a short practical bullet list (hours, cost, coords) when available.
- Be local, warm, and avoid being overly formal.
"""


def get_main_prompt() -> ChatPromptTemplate:
    """Returns the main chat prompt template."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT + "\nخلاصه مکالمه: {memory}\n"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
        ]
    )


# --- Summarization Prompt ---
SUMMARIZE_PROMPT = ChatPromptTemplate.from_template(
    """
Summarize this conversation history in 1-2 Persian sentences, focusing on key topics, user queries, and any ongoing context about Qeshm Island. Keep it concise and relevant for future responses.

History:
{history_text}
"""
)

# --- Routing Prompt ---
# Using a dedicated prompt for routing is cleaner than a simple f-string.
# (Note: The original code used llm.invoke directly, this is a structured alternative
# but to preserve logic *exactly*, we will let utils.py continue to build it dynamically.
# This prompt is here for future improvement.)
ROUTING_PROMPT_TEMPLATE = """Classify the user's query for the Qeshm AI assistant.
Respond with only one word: 'rag' (for local info, places, facts), 'google' (for fresh news, specific/unknown facts, or web search), or 'chat' (for casual conversation, greetings).

Conversation Memory: {memory}
User Query: {query}
Classification:"""
