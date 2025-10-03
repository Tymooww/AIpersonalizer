from langchain_core.prompts import PromptTemplate
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
import requests
from langchain_core.tools import tool
from dotenv import load_dotenv
import os


def initialize():
    chosen_llm = ChatOllama(base_url='http://localhost:11434', model="mistral")
    load_dotenv()
    cms_config = {
        "base_url": os.getenv("CONTENTSTACK_URL"),
        "api_key": os.getenv("CONTENTSTACK_API_KEY"),
        "delivery_token": os.getenv("CONTENTSTACK_DELIVERY_TOKEN"),
        "management_token": os.getenv("CONTENTSTACK_MANAGEMENT_TOKEN"),
        "environment": os.getenv("CONTENTSTACK_ENVIRONMENT")
    }

    config = {"llm": chosen_llm, "cms": cms_config}
    print("Connected CMS: " + cms_config["base_url"])
    print("Connected LLM: " + chosen_llm.model)
    return config


@tool
def retrieve_pages(content_type_uid: str) -> list:
    """Retrieves all pages from ContentStack with the Content Delivery API"""
    print("API " + config_variables["cms"]["api_key"] + " connected.")
    headers = {
        "api_key": config_variables["cms"]["api_key"],
        "access_token": config_variables["cms"]["delivery_token"],
        "Content-Type": "application/json"
    }

    params = {
        "environment": config_variables["cms"]["environment"]
    }

    url = f"https://{config_variables['cms']['base_url']}/v3/content_types/{content_type_uid}/entries"

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        page_list = response.json()
        return page_list
    except requests.exceptions.RequestException as e:
        return f"Error retrieving pages: {str(e)}"


@tool
def customize_landing_page():
    """Customize landing page."""
    # POST request for editing landing page
    return None


@tool
def customize_standard_page():
    """Customize page."""
    # POST request for editing page
    return None


config_variables = initialize()
agent = create_react_agent(model=config_variables["llm"], tools=[retrieve_pages])
result = agent.invoke({"messages": [("user",
                                     "Give me the pages stored in ContentStack. You can do this using the content_type_uid what is 'page'. Answer with the full list, nothing more.")]})

pages_data = result["messages"][-1].content
print(pages_data)
