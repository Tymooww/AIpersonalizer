"""This agent retrieves all pages (with uid 'page') from ContentStack."""
from typing import TypedDict
from dotenv import load_dotenv
from langgraph.graph import StateGraph
import os
import requests


# region Initialization of LLM and CMS
def initialize_config():
    load_dotenv()
    cms_config = {
        "base_url": os.getenv("CONTENTSTACK_URL"),
        "api_key": os.getenv("CONTENTSTACK_API_KEY"),
        "delivery_token": os.getenv("CONTENTSTACK_DELIVERY_TOKEN"),
        "management_token": os.getenv("CONTENTSTACK_MANAGEMENT_TOKEN"),
        "environment": os.getenv("CONTENTSTACK_ENVIRONMENT")
    }

    config_variables = {"cms": cms_config}
    print("Connected CMS: " + cms_config["base_url"])

    return config_variables


# endregion

# region Langgraph nodes
class AgentState(TypedDict):
    messages: list
    pages_list: dict
    content_type_uid: str
    entry_to_customize: str
    block_index_to_customize: int


def retrieve_pages_node(state: AgentState):
    """Retrieve all existing pages from ContentStack"""
    headers = {
        "api_key": config["cms"]["api_key"],
        "access_token": config["cms"]["delivery_token"],
        "Content-Type": "application/json"
    }

    params = {
        "environment": config["cms"]["environment"]
    }

    url = f"https://{config['cms']['base_url']}/v3/content_types/{state['content_type_uid']}/entries"
    print("API " + url + f" contacted with stack {config['cms']['api_key']}.")
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        page_list = response.json()

        state['pages_list'] = page_list
        return state
    except requests.exceptions.RequestException as e:
        return f"Error retrieving pages: {str(e)}"


# endregion

# Initialize LLM and CMS
config = initialize_config()

# Create graph
graph = StateGraph(AgentState)
graph.add_node("RetrievePages", retrieve_pages_node)
graph.set_entry_point("RetrievePages")
graph.set_finish_point("RetrievePages")

retrievalAgent = graph.compile()

# Run agent
result = retrievalAgent.invoke({"content_type_uid": "page"})
print(result["pages_list"])
