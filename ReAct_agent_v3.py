"""This agent retrieves all pages (with uid 'page') from ContentStack and personalizes them using tools."""
from typing import Annotated, Sequence, TypedDict
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import BaseMessage
from langchain_core.messages import ToolMessage
from langchain_core.messages import SystemMessage
from langgraph.graph.message import add_messages
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
        api_base=os.getenv("BONZAI_URL")
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
def personalize_texts(generic_blocks:str, customer_background:str) -> str:
    """Personalize marketing text based on generic content and customer's background."""
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
def personalize_images(generic_blocks: str, assets:str, customer_background: str) -> str:
    """Personalize image(s) of a page based on the customer's background."""
    print("Personalizing image(s) for block(s)...")
    personalized_blocks = config["llm"].invoke(f"""Choose an image from the asset list that matches the context of the page and fits with the customer's background. To do this look at the tags, title and description. 
            Make a top 3 of most suitable images and then analyse the image via the URL. When chosen make sure the image exists in the asset_list. You can use the generic blocks to know what the context of the page is.
            It is very important that the image always fits with the context of the page, if you cannot find an image that suits the customer's background then choose an image that suits the context best.
            Use the received block(s) as a formatting structure and return new block(s) with the correct image information of the new image. Make sure that you do not change or add anything besides the image information and 
            that you copy all information of the chosen image from the asset list to the new block(s), this includes the uid, is_dir, version, ACL, content_type, created_at, created_by, description, file_size, filename, 
            parent_uid, tags, title, updated_at, updated_by, publish_details, url and layout. Give only the generated object as a response, nothing else.

            Information you can use:
            Generic blocks: {generic_blocks}
            Customer_background: {customer_background}
            Asset_list: {assets}""")

    return str(personalized_blocks)

@tool
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

tools = [personalize_texts, personalize_images, personalize_element_order]
# endregion

# region Langgraph nodes
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    page_list: dict
    asset_list: dict
    content_type_uid: str
    generated_page: str


def fetch_data_node(state: AgentState):
    """Retrieve all pages and assets from ContentStack."""
    # Create API call
    headers = {
        "api_key": config["cms"]["api_key"],
        "access_token": config["cms"]["delivery_token"],
        "Content-Type": "application/json"
    }

    params = {
        "environment": config["cms"]["environment"],
        "include[]": "header_reference"
    }

    retrieve_pages_url = f"https://{config['cms']['base_url']}/v3/content_types/{state['content_type_uid']}/entries"
    retrieve_assets_url = f"https://{config['cms']['base_url']}/v3/assets"

    # Retrieve pages from ContentStack
    try:
        response = requests.get(retrieve_pages_url, headers=headers, params=params)
        response.raise_for_status()
        page_list = response.json()

        state['page_list'] = page_list
        print("Retrieved pages from CMS.")
    except requests.exceptions.RequestException as e:
        return f"Error retrieving pages: {str(e)}"

    # Retrieve assets from ContentStack
    try:
        response = requests.get(retrieve_assets_url, headers=headers, params=params)
        response.raise_for_status()
        asset_list = response.json()

        state['asset_list'] = asset_list
        print("Retrieved assets from CMS.")
        return state
    except requests.exceptions.RequestException as e:
        return f"Error retrieving assets: {str(e)}"


def personalize_page_node(state: AgentState):
    """Personalize a page to the customer's background."""
    personalizer_agent = create_react_agent(config["llm"], tools)

    prompt = {
        "messages": [("user", f"""Personalize the our services page by personalizing the text and then the image. Your steps should be as follows:
        1. Personalize the marketing text using the customer's interests and the page list.
        2. Use the returned blocks to generate a new page object using the our-services page from the page list as a template and replacing the old text with the updated text. Make sure that you do not change or add anything besides the personalized text.
        3. Personalize the image using the customer's interests, the page list and the asset list.
        4. Use the personalized blocks to generate a new page object by using the page from step 2 as a template and filling in the updated image information. Make sure that you do not change or add anything besides the image information.
         Give only the generated object as an answer, nothing else.

            Information you can use:
            Customer interests: The user works at a construction company. 
            Page list: {state['page_list']}
            Asset list: {state['asset_list']}
            """)]}

    # Generate marketing text with agent
    try:
        print("Personalizer agent starts personalizing...")
        response = personalizer_agent.invoke(prompt)
        response = response['messages'][-1].content

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
graph.add_node("FetchData", fetch_data_node)
graph.add_node("personalizePage", personalize_page_node)
graph.add_edge(START, "FetchData")
graph.add_edge("FetchData", "personalizePage")
graph.add_edge("personalizePage", END)

personalizationAgent = graph.compile()

# Run agent
result = personalizationAgent.invoke({"content_type_uid": "page"})

