from google.adk.agents import Agent
from google.adk.tools import google_search

from .prompt import research_agent_instruction

research_agent = Agent(
    model="gemini-2.5-flash",
    name="research_agent",
    description=(
        """
    A market researcher for an e-commerce site.
    Receives a search request from a user, and returns a list of 5 generated queries in English.
    """
    ),
    instruction=research_agent_instruction,
    tools=[google_search],
)