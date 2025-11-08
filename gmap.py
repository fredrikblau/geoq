import os, json
from dotenv import load_dotenv

# Note: Ensure all tools (google_search_tool, google_places_tool) are defined as shown above
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
from langchain_community.tools import GooglePlacesTool

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

# Define the Google Maps tool structure
# This is also a built-in tool that Gemini can use internally.
google_maps_tool = {"googleMaps": {}}

llm_with_maps = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=GEMINI_API_KEY,
    model_kwargs={"tools": [google_maps_tool]},
)

# You can optionally provide user location for 'near me' queries
# location_tool_config = {"googleMaps": {"location": {"lat": 34.0522, "lng": -118.2437}}}
# llm_with_maps = ChatGoogleGenerativeAI(model="gemini-2.5-flash", tools=[location_tool_config])


prompt = "قشم کجا بیلیارد میشه بازی کرد؟"
response = llm_with_maps.invoke(prompt, tools=[{"google_search": {}}])

print(response.content)
