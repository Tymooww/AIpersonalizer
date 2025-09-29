''' This agent retrieves all pages (with uid 'page') from ContentStack and personaliz'''
from typing import Annotated, Sequence, TypedDict
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage
from langchain_core.messages import ToolMessage
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.graph.message import add_messages
from langchain_litellm import ChatLiteLLM
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent
import os
import requests



# region Initialization of LLM and CMS
def initialize_config():
    load_dotenv()

    llm_config = ChatLiteLLM(
        model = os.getenv("BONZAI_MODEL"),
        api_key = os.getenv("BONZAI_API_KEY"),
        api_base= os.getenv("BONZAI_URL"),
        custom_llm_provider="openai"
    )

    cms_config = {
        "base_url": os.getenv("CONTENTSTACK_URL"),
        "api_key": os.getenv("CONTENTSTACK_API_KEY"),
        "delivery_token": os.getenv("CONTENTSTACK_DELIVERY_TOKEN"),
        "management_token": os.getenv("CONTENTSTACK_MANAGEMENT_TOKEN"),
        "environment": os.getenv("CONTENTSTACK_ENVIRONMENT")
    }

    config_variables = {"llm": llm_config, "cms": cms_config}
    print("Connected CMS: " + config_variables["cms"]["base_url"])
    print("Connected LLM: " + config_variables["llm"].model)

    return config_variables


# endregion

# region Langgraph nodes
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    generated_content: str
    pages_list: dict
    content_type_uid: str
    entry_to_customize: str
    block_index_to_customize: int

@tool
def personalize_informational_text(pageuid: str, generated_content: str):
    """Personalize the information of a product in ContentStack"""
    print("Informational text personalization result: " + result)

    # state['block_index_to_customize'] = 0 # Set block index to two (second block will be edited)

    headers = {
        "api_key": config["cms"]["api_key"],
        "authorization": config["cms"]["management_token"],
        "Content-Type": "application/json"
    }

    body = {
        "entry": {
            "blocks": {
                "UPDATE": {
                    "index": 0,
                    "data": {
                        "block": {
                            "copy": {generated_content},
                        }
                    }
                }
            }
        }
    }

    url = f"https://{config['cms']['base_url']}/v3/content_types/page/entries/{pageuid}"
    print("Personalized content at " + url + f" in stack {config['cms']['api_key']}.")

    try:
        response = requests.put(url, headers=headers, json=body)
        response.raise_for_status()
        response = response.json()

        return response
    except requests.exceptions.RequestException as e:
        return f"An error occured when updating pages: {str(e)}"

# Create toollist and initialize LLM and CMS
tools = [personalize_informational_text]
config = initialize_config()

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
    print("Received pages from " + url + f" in stack {config['cms']['api_key']}.")
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        page_list = response.json()

        state['pages_list'] = page_list
        return state
    except requests.exceptions.RequestException as e:
        return f"Error retrieving pages: {str(e)}"


def personalize_page(state: AgentState):
    """Personalize a page"""

    agent = create_react_agent(config["llm"], tools)

    '''Personalize the landing page by generating a personalized informational text. There are a few steps you have to follow:
            1. Find the landing page in the pages list and look at the second block contents and remember the uid of the page
            2. Generate a well-suited informational text based on the content of the second block and the user's interests
            3. Use this uid together with your tools to change the information of the product in ContentStack.'''

    prompt = {
            "messages": [("user", f"""Find the landing page in the pages list and look at the second block contents. Generate a new marketing text for it tailored to the user's interests.
            Give your response like this:
            Found content: <The content you saw in the second block of the landing page>
            Personalized marketing text: <Your new marketing text>

            Information you can use:
            User interests: The user works at a construction company. 
            Pages list: {state['pages_list']}
            """)]}

    # Generate informational text with agent
    try:
        result = agent.invoke(prompt)

        print(result)
        state["generated_content"] = result

        return state
    except requests.exceptions.RequestException as e:
        return f"An error occured when generating the informational text: {str(e)}"

    # TODO: dynamically personalize components:
    # personalize header tailored to industry/interests
    # personalize informational text tailored to industry/interests
    # personalize recommendations (what page most relevant for person) --> Example Bibby: Construction worker should have construction as first option.



# endregion

# Create graph
graph = StateGraph(AgentState)
graph.add_node("RetrievePages", retrieve_pages_node)
graph.add_node("personalizePage", personalize_page)
graph.add_edge(START, "RetrievePages")
graph.add_edge("RetrievePages", "personalizePage")
graph.add_edge("personalizePage", END)

retrievalAgent = graph.compile()

# Run agent
result = retrievalAgent.invoke({"content_type_uid": "page"})
print(result["pages_list"])









