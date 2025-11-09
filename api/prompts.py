from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

SYSTEM_PROMPT = """
You are a friendly, local AI assistant for Qeshm Island, Iran. Answer in Persian (فارسی).
- Use provided context documents (labeled [source:id]) when relevant.
- If the context doesn't contain the answer, say you don't know and offer to search the web.
- Prefer descriptive and helpful answers (3-6 sentences) and finish with a short practical bullet list (hours, cost, coords) when available.
- Be local, warm, and avoid being overly formal.
"""


def get_main_prompt():
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT + "\nخلاصه مکالمه: {memory}\n"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
        ]
    )
