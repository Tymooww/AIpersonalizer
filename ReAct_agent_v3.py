"""This agent retrieves all pages (with uid 'page') from ContentStack and personalizes them using tools."""
from typing import TypedDict
from dotenv import load_dotenv
from langchain_core.tools import tool
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
        model=os.getenv("BONZAI_MODEL"),
        api_key=os.getenv("BONZAI_API_KEY"),
        api_base=os.getenv("BONZAI_URL"),
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
def personalize_marketing_text(generic_blocks:str, customer_background:str) -> str:
    """Personalize marketing text based on generic content and customer background."""
    print("Generating personalized text for block(s)...")
    personalized_blocks = config["llm"].invoke(f"""Generate a new marketing text for the provided generic blocks, based on the content that is currently in there, by tailoring it to the customer's background. 
            It is very important to keep in mind that you may not twist the meaning of the content. While it should be a text that shows how the product can fit in the customer's interests, it should still advertise the product the content states.
            Use the received block(s) as a formatting structure and return new block(s) with the generated text. Make sure that you do not change or add anything besides the personalized text. 
            Give only the generated object as a response, nothing else.
            
            Information you can use:
            Generic blocks: {generic_blocks}
            customer_background: {customer_background}""")

    # TODO: Update generated page somehow
    return str(personalized_blocks)


@tool
def personalize_hero_image(generic_blocks: str, customer_background: str) -> str:
    """Personalize the hero image of a page based on the customer background."""
    # TODO: Implement personalizing the hero image
    '''print("Generating personalized text for block(s)...")
    personalized_blocks = config["llm"].invoke(f"""Generate a new marketing text for the provided generic blocks, based on the content that is currently in there, by tailoring it to the customer's background. 
            It is very important to keep in mind that you may not twist the meaning of the content. While it should be a text that shows how the product can fit in the customer's interests, it should still advertise the product the content states.
            Use the received block(s) as a formatting structure and return new block(s) with the generated text. Make sure that you do not change or add anything besides the personalized text. 
            Give only the generated object as a response, nothing else.

            Information you can use:
            Generic blocks: {generic_blocks}
            customer_background: {customer_background}""")'''

    return

tool
def personalize_element_order(generic_blocks: str, customer_background: str) -> str:
    """Personalize the order of elements of a page, based on the customer background."""
    # TODO: Implement personalizing the order of elements
    '''print("Generating personalized text for block(s)...")
    personalized_blocks = config["llm"].invoke(f"""Generate a new marketing text for the provided generic blocks, based on the content that is currently in there, by tailoring it to the customer's background. 
            It is very important to keep in mind that you may not twist the meaning of the content. While it should be a text that shows how the product can fit in the customer's interests, it should still advertise the product the content states.
            Use the received block(s) as a formatting structure and return new block(s) with the generated text. Make sure that you do not change or add anything besides the personalized text. 
            Give only the generated object as a response, nothing else.

            Information you can use:
            Generic blocks: {generic_blocks}
            customer_background: {customer_background}""")'''

    return

tools = [personalize_marketing_text, personalize_hero_image, personalize_element_order]


# endregion

# region Langgraph nodes
class AgentState(TypedDict):
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
    personalizer_agent = create_react_agent(config["llm"], tools)

    prompt = {
        "messages": [("user", f"""Personalize the our services page with personalized marketing text by sending it the blocks of the page. 
        Use the personalized blocks you will receive to generate a new page object using the page from the page list as a template and filling in the updated content. 
        Make sure that you do not change or add anything besides the personalized text. Give only the generated object as an answer, nothing else.

            Information you can use:
            Customer interests: The user works at a construction company. 
            Page list: {state['page_list']}
            """)]}

    # Generate marketing text with agent
    try:
        print("Personalizer agent starts personalizing...")
        response = personalizer_agent.invoke(prompt)
        response = response['messages'][-1].content
        print("Personalizer agent personalized a page.")

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
