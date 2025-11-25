from google.adk.agents import Agent
from google.adk.tools import AgentTool, FunctionTool, google_search
from .tools import search_items_with_filters, search_reviews_with_filters, summarize_reviews  
from .sub_agents import bigquery, research
from .prompt import shop_agent_instruction


root_agent = Agent(
    name="conversational_search_agent",
    model="gemini-2.5-flash",
    instruction=shop_agent_instruction,
    description="An agent that helps customers to assist in conversational search",
    tools=[AgentTool(agent=research.research_agent),AgentTool(agent=bigquery.agent.root_agent), FunctionTool(func=search_items_with_filters), FunctionTool(func=search_reviews_with_filters), FunctionTool(func=summarize_reviews)]
)