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
from pymongo import MongoClient
import json


# region Initialization
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

    db_config = {
        "client": MongoClient(os.getenv("MONGODB_URL")),
        "db_name": os.getenv("MONGODB_DATABASE")
    }

    config_variables = {"llm": llm_config, "cms": cms_config, "db": db_config}

    print("Connected CMS: " + config_variables["cms"]["base_url"])
    print("Connected LLM: " + config_variables["llm"].model)

    try:
        config_variables["db"]["client"].admin.command('ping')
        print("Connected DB: " + str(config_variables["db"]["client"]))
    except Exception as e:
        print(f"Couldn't connect to MongoDB: {e}")

    return config_variables

config = initialize_config()
# endregion

# region agentic tools
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
tools = [personalize_informational_text]
# endregion

# region Langgraph nodes
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    generated_page: str
    page_list: dict
    content_type_uid: str

def retrieve_pages_node(state: AgentState):
    """Retrieve all existing pages from ContentStack"""
    headers = {
        "api_key": config["cms"]["api_key"],
        "access_token": config["cms"]["delivery_token"],
        "Content-Type": "application/json"
    }

    params = {
        "environment": config["cms"]["environment"],
        "include[]": "header_reference"
    }

    url = f"https://{config['cms']['base_url']}/v3/content_types/{state['content_type_uid']}/entries"

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        page_list = response.json()

        state['page_list'] = page_list
        print("Retrieved pages from CMS.")
        return state
    except requests.exceptions.RequestException as e:
        return f"Error retrieving pages: {str(e)}"


def personalize_page_node(state: AgentState):
    """Personalize a page"""
    agent = create_react_agent(config["llm"], [])

    prompt = {
            "messages": [("user", f"""Find the our-services page in the pages list and look at the block contents. Generate a new marketing text for it, based on the content that is currently in there, and it should be tailored to the user's interests. 
            It is very important to keep in mind that you may not twist the meaning of the content, while it should be a text that shows how the product can fit in the user's interests, it should still advertise the product the content states.
            Use your updated text to generate a new page object using the page from the page list as a template and filling in the updated content. Make sure that you do not change or add anything besides the personalized text.
            Give only the generated object as an answer, nothing else.

            Information you can user:
            User interests: The user works at a construction company. 
            Pages list: {state['page_list']}
            """)]}

    # Generate marketing text with agent
    try:
        result = agent.invoke(prompt)
        response = result['messages'][-1].content

        # Create json object from the response
        try:
            generated_object = response.replace('```json', '').replace('```', '').strip()
            generated_page = json.loads(generated_object)
            print("Personalized a page: " + str(generated_page))
        except Exception as e:
            return f"Agent response could not be pocessed: {str(e)}. Agent response: {generated_page}"

    except Exception as e:
        return f"An error occured when generating content: {str(e)}"

    # Save generated page
    state['generated_page'] = generated_page

    database = config["db"]["client"][config["db"]["db_name"]]
    collection = database['pages']

    result = collection.insert_one(generated_page)
    print(f"Saved personalized page in database with ID: {result.inserted_id}")
    return state
# endregion

# Create graph
graph = StateGraph(AgentState)
graph.add_node("RetrievePages", retrieve_pages_node)
graph.add_node("personalizePage", personalize_page_node)
graph.add_edge(START, "RetrievePages")
graph.add_edge("RetrievePages", "personalizePage")
graph.add_edge("personalizePage", END)

retrievalAgent = graph.compile()

# Run agent
result = retrievalAgent.invoke({"content_type_uid": "page"})
print(result["page_list"])









