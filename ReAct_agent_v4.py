"""This agent personalizes ContentStack pages by personalizing text and choosing the best fitting image for a page."""
from typing import TypedDict
from dotenv import load_dotenv
from langchain_litellm import ChatLiteLLM
from langgraph.graph import StateGraph, START, END
import os
import requests
from pymongo import MongoClient
from pydantic import BaseModel, Field


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

# region Langgraph nodes
class AgentState(TypedDict):
    content_type_uid: str
    page_list: dict
    asset_list: dict
    generic_page: dict
    personalized_page: dict
    personalization_queue: list

def fetch_data_node(state: AgentState):
    """Retrieve all pages and assets from ContentStack."""
    # Create API calls
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

        state["page_list"] = page_list
        print("Retrieved pages from CMS")
    except requests.exceptions.RequestException as e:
        return f"An error occurred while retrieving pages: {str(e)}"

    # Setup personalization queue and extract page to personalize
    state["personalization_queue"] = ["text", "image", "save"] # TODO: This will be replaced by an agent deciding the steps to execute

    # Extract the page to customize
    state["generic_page"] = state["page_list"]["entries"][2]  # TODO: This will be replaced by an agent deciding what pages to personalize
    state["personalized_page"] = state["page_list"]["entries"][2] # TODO: This will be replaced by an agent deciding what pages to personalize

    # Retrieve assets from ContentStack
    try:
        response = requests.get(retrieve_assets_url, headers=headers, params=params)
        response.raise_for_status()
        asset_list = response.json()

        state["asset_list"] = asset_list
        print("Retrieved assets from CMS")

        return state
    except requests.exceptions.RequestException as e:
        return f"An error occurred while retrieving assets from CMS: {str(e)}"

def personalization_router_node (state:AgentState):
    """Router node for logging."""
    if len(state["personalization_queue"]) > 0:
        print(f"Next step: {state['personalization_queue'][0]}")
    else:
        print("Personalization process is finished")

    return state

def determine_next_step (state: AgentState):
    """Route to the next step of the personalization process."""
    if len(state["personalization_queue"]) != 0:
        match state["personalization_queue"][0]:
            case "text":
                return "p_texts"
            case "image":
                return "p_images"
            case "save":
                return "save"
    else:
        return "end"

def personalize_texts_node (state:AgentState):
    """Personalize text(s): generate a tailored text based on the content of the generic page and the customer's background."""
    # Remove step from queue
    state["personalization_queue"].pop(0)
    print("Personalizing text...")

    # Define output structure
    class GeneratedText(BaseModel):
        generated_text: str = Field(description="The generated marketing text.")
        why_better: str = Field(description="The reason why this text is better.")

    # Generate personalized text
    try:
        generated_text = config["llm"].with_structured_output(GeneratedText).invoke(f"""Generate a new marketing text in HTML for the provided generic page by tailoring it to the customer's background, based on the content that is currently in there. 
                It is very important to keep in mind that you may not twist the meaning of the content. While it should be a text that shows how the product can fit in the customer's background, it should still advertise the product the content states.
                Return only the new marketing text and the reason why the text is better, nothing else.

                Information you can use:
                Generic page: {state['generic_page']}
                Customer information: customer works in the construction industry.""")

        print("Personalized text: " + str(generated_text.why_better))

        # Update the copy of the page to the generated text
        state["personalized_page"]["blocks"][0]["block"]["copy"] = generated_text.generated_text
        return state

    except Exception as e:
        print(f"An error occurred when personalizing the text of a page: {str(e)}")
        state["personalized_page"] = {"Error" : str(e)}
        return state

def personalize_images_node (state:AgentState):
    """Personalize image(s): choose the best fitting image for the content of the page and the customer's background."""
    # Remove step from queue
    state["personalization_queue"].pop(0)
    print("Personalizing image...")

    # Strip assets information to essential data for LLM
    stripped_asset_list = []
    for asset in state["asset_list"]["assets"]:
        stripped_asset = {"title": asset.get("title", "No title found"), "filename": asset.get("filename"), "description": asset.get("description", "No description found"), "tags": asset.get("tags", [])}
        stripped_asset_list.append(stripped_asset)

    # Define output structure
    class Image(BaseModel):
        title: str = Field(description="The title of the chosen image.")
        choice_reason: str = Field(description="The reason why you chose the image.")

    try:
        chosen_image = config["llm"].with_structured_output(Image).invoke(f"""Personalize the image of the provided page by choosing the best fitting image from the image list. 
                The image should match the context of the page and the customer's background. To do this, analyze the tags, title, filename and description for each image and choose the best fitting image based on the criteria defined above. 
                It is very important that the image always fits the context of the page, if you can't find an image that suits both the customer's background and the content of the page, then choose an image that suits the context best. 
                Return only the name of the chosen image and the reason why you chose it, nothing else. Make sure that you use the exact name of the chosen image, check that your chosen title is in the image list.
                
                Information you can use:
                Generic page: {state['generic_page']}
                Image list: {stripped_asset_list}
                Customer information: customer works in the construction industry.""")

        print("Personalized image: " + str(chosen_image))

        # Retrieve details of chosen image
        chosen_image_details = None
        for image in state["asset_list"]["assets"]:
            if image["title"] == chosen_image.title:
                chosen_image_details = image

        # Update the image of the page to the chosen image
        if chosen_image_details is not None:
            state["personalized_page"]["blocks"][0]["block"]["image"] = chosen_image_details
        else:
            print(f"An error occurred when personalizing the image of a page: The chosen image does not exist: {chosen_image.title}")
            state["personalized_page"] = {"Error" : f"Error: chosen image does not exist ({chosen_image.title})"}
        return state

    except Exception as e:
        print(f"An error occurred when personalizing the image of a page: {str(e)}")
        state["personalized_page"] = {"Error" : str(e)}
        return state

def save_personalized_page_node (state:AgentState):
    """Save the personalized page in the database."""
    # Remove step from queue
    state["personalization_queue"].pop(0)
    print("Saving personalized page...")

    # Prepare database connection
    database = config["db"]["client"][config["db"]["db_name"]]
    collection = database["pages"]

    try:
        generated_page = state["personalized_page"]

        # Check if an error occurred during the personalization process
        if "Error" in generated_page:
            print(f"Page not saved in database, because of an error during personalization: {generated_page}")
            return state

        # Save personalized page in the database
        if collection.count_documents({'title': generated_page["title"]}) == 0:
            response = collection.insert_one(generated_page)
            print(f"Saved personalized page in database with ID: {response.inserted_id}")
        else:
            # Replace the page if it already exists
            response = collection.replace_one(
                {'title': generated_page['title']},
                generated_page
            )
            print(f"Updated personalized page in database")

    except Exception as e:
        print(f"An error occurred while saving the personalized page: {str(e)}")
        return state
# endregion

# Create graph
graph = StateGraph(AgentState)
graph.add_node("FetchData", fetch_data_node)
graph.add_node("PersTexts", personalize_texts_node)
graph.add_node("PersImages", personalize_images_node)
graph.add_node("Router", personalization_router_node)
graph.add_node("SavePersPage", save_personalized_page_node)

graph.add_edge(START, "FetchData")
graph.add_edge("FetchData", "Router")
graph.add_conditional_edges(
    "Router",
    determine_next_step,
    {
        "p_texts": "PersTexts",
        "p_images": "PersImages",
        "save": "SavePersPage",
        "end": END
    }
)
graph.add_edge("PersTexts", "Router")
graph.add_edge("PersImages", "Router")
graph.add_edge("SavePersPage", END)
personalizationAgent = graph.compile()

# Run agent
result = personalizationAgent.invoke({"content_type_uid": "page"})

