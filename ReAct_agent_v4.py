"""This agent personalizes ContentStack pages by personalizing text, choosing the best fitting image and reordering blocks (if necessary) for a page."""
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
    is_retry_step: bool


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
    state["personalization_queue"] = ["text", "image", "order", "save"] # TODO: This will be replaced by an agent deciding the steps to execute

    # Extract the page to customize
    state["generic_page"] = state["page_list"]["entries"][0]  # TODO: This will be replaced by an agent deciding what pages to personalize
    state["personalized_page"] = state["page_list"]["entries"][0] # TODO: This will be replaced by an agent deciding what pages to personalize
    state["is_retry_step"] = False

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
    if len(state["personalization_queue"]) > 1:
        print(f"Next step: {state['personalization_queue'][0]}")
    else:
        print("Page has been personalized successfully")

    return state

def determine_next_step (state: AgentState):
    """Route to the next step of the personalization process."""
    if len(state["personalization_queue"]) != 0:
        match state["personalization_queue"][0]:
            case "text":
                return "p_texts"
            case "image":
                return "p_images"
            case "order":
                return "p_order"
            case "save":
                return "save"

    else:
        return "end"

def personalize_texts_node (state:AgentState):
    """Personalize text(s): generate a tailored text based on the content of the generic page and the customer's background."""
    print("Personalizing text...")

    # Define output structure
    class GeneratedText(BaseModel):
        title: str = Field(description="The generated title.")
        copytext: str = Field(description="The generated copy text.")
        explanation: str = Field(description="The reason why this text is better.")

    # Generate personalized texts for block
    try:
        generated_titles = []
        generated_copy_texts = []

        for block in state["generic_page"]["blocks"]:
            generated_text = config["llm"].with_structured_output(GeneratedText).invoke(f"""
                    You are an expert in personalized marketing.
                    Your task: use "Customer information" to personalize the copytext and title of "Block to personalize". 
                    Important: 
                    1. Don't personalize too much, you never know if a CDP has perfect information about the customer. 
                    2. Use the customer information to show the customer what challenges or needs the product can help with, but don't use terms from the industry or terms like tailored in the texts or titles.  
                    3. Ensure that the original meaning of the content is preserved, sell the stated products, don't invent new products or product variations.
                    4. Maintain a professional tone.  
                    5. Only use the provided facts and improve the wording, do not hallucinate or assume things about the customer or products or reinvent what is written in the "Block to personalize"..
                    6. Write the copy in HTML.
                    
                    Please provide as your answer:
                    1. Title: the personalized title
                    2. Copytext: the personalized copytext
                    3. A brief explanation of why you created the new title and copytext, focused on the main improvements.

                    Information you can use:
                    Block to personalize: {block}.
                    Customer information: Industry: IT Cloud computing.
            """)

            generated_titles.append(generated_text.title)
            generated_copy_texts.append(generated_text.copytext)

            print("Personalized text: " + str(generated_text))

        # Update the copy of the page to the generated text
        for block_id, _ in enumerate(state["generic_page"]["blocks"]):
            state["personalized_page"]["blocks"][block_id]["block"]["copy"] = generated_copy_texts[block_id]
            state["personalized_page"]["blocks"][block_id]["block"]["title"] = generated_titles[block_id]

        # Remove step from personalization queue
        state["personalization_queue"].pop(0)
        state["is_retry_step"] = False
        return state

    except Exception as e:
        if state["is_retry_step"]:
            state["personalization_queue"] = []
            print(f"An error occurred when personalizing the text of a page: {str(e)}")
            state["personalized_page"] = {"Error": str(e)}
        else:
            print(f"An error occurred when personalizing the text of a page, trying again. Error message: {str(e)}")
            state["is_retry_step"] = True
        return state



def personalize_images_node (state:AgentState):
    """Personalize image(s): choose the best fitting image for the content of the page and the customer's background."""
    print("Personalizing image...")

    # Strip assets information to essential data for LLM
    stripped_asset_list = []
    for asset in state["asset_list"]["assets"]:
        stripped_asset = {"title": asset.get("title", "No title found"), "filename": asset.get("filename"), "description": asset.get("description", "No description found"), "tags": asset.get("tags", [])}
        stripped_asset_list.append(stripped_asset)

    # Define output structure
    class Image(BaseModel):
        titles: list = Field(description="The list with the titles of the chosen images.")
        block_uids: list = Field(description="The list with the UIDs of the blocks where the chosen images should be put.")
        explanation: str = Field(description="The explanation of why you chose these images and why you placed them in the blocks you chose.")

    try:
        response = config["llm"].with_structured_output(Image).invoke(f"""
                You are an expert in personalized marketing.
                Your task: use "Customer information" and "Image list" to find the best fitting image(s) for the blocks in "Block list". 
                Important: 
                1. Analyze all images in "Image list" to find fitting images.
                2. You can analyze images by looking at their title, filename, description and tags.
                3. The image you choose must fit the title and/or copy of the block, if possible it should also fit with the customer's interests.
                4. It is mandatory to have at least one block with an image, more blocks with an image are allowed.
                5. A block can only have one image.
                6. Every image needs to have a block to be displayed in, so there should be as many block UIDs as titles
                7. You can find the UID of a block in _metadata.
                8. Make sure that your chosen title(s) exist in "Image list", don't invent new titles but copy them over.
                9. Make sure that your chosen UID(s) exist in "Block list", don't invent new UIDs but copy them over.
                    
                Please provide as your answer:
                1. Title: this title is from the image you want to place.
                2. Block UID: this UID is from the block you want to place the image.
                3. A brief explanation of why you chose these images and why you placed them in the blocks you chose, focused on the main improvements.

                Information you can use:
                Block list: {state['generic_page']["blocks"]}.
                Image list: {stripped_asset_list}
                Customer information: Industry: IT Cloud computing.
        """)

        print("Personalized image: " + str(response))

        # Retrieve details of chosen image(s)
        image_details = []
        for title in response.titles:
            for image in state["asset_list"]["assets"]:
                if image["title"] == title:
                    image_details.append(image)
                    break

        # Retrieve details of chosen block(s)
        block_details = []
        for uid in response.block_uids:
            for block in state["generic_page"]["blocks"]:
                if block["block"]["_metadata"]["uid"] == uid:
                    block_details.append(block)
                    break

        # Update chosen blocks with new images
        if len(block_details) != 0:
            for index, block in enumerate(block_details):
                block["block"]["image"] = image_details[index]
        else:
            if state["is_retry_step"]:
                state["personalization_queue"] = []
                print(f"An error occurred when personalizing the image of a page: one or more of the chosen images ({response.titles}) or blocks ({response.block_uids})do not exist.")
                state["personalized_page"] = {"Error": f"Error: one or more of the chosen images ({response.titles}) or blocks ({response.block_uids}) do not exist."}
            else:
                print(f"One or more of the chosen images ({response.titles}) or blocks ({response.block_uids}) do not exist, trying again.")
                state["is_retry_step"] = True
            return state

        # Remove step from personalization queue
        state["personalization_queue"].pop(0)
        state["is_retry_step"] = False
        return state

    except Exception as e:
        if state["is_retry_step"]:
            state["personalization_queue"] = []
            print(f"An error occurred when personalizing the image of a page: {str(e)}")
            state["personalized_page"] = {"Error": str(e)}
        else:
            print(f"An error occurred when personalizing the image of a page, trying again. Error message: {str(e)}")
            state["is_retry_step"] = True
        return state

def personalize_element_order_node (state:AgentState):
    """Change the order of blocks on a page: change the blocks based on the content of the generic page and the customer's background."""
    print("Personalizing order of elements...")

    # Define output structure
    class GeneratedOrder(BaseModel):
        block_order: list = Field(description="The order of the blocks by page uid.")
        explanation: str = Field(description="The reason why this order is better.")

    # Generate personalized text
    try:
        response = config["llm"].with_structured_output(GeneratedOrder).invoke(f"""
                You are an expert in personalized marketing.
                Your task: use "Customer information" and "Block list" to create a personalized order for the blocks of the provided page.
                Important: 
                1. Use "Customer information" to decide what blocks are the most relevant for the customer.
                2. Place the most relevant blocks first in the order.
                3. The first block always needs to be first.
                4. All blocks need to be in the list, so the amount of blocks in the Block list should be the same as the amount of UIDs given in the answer.
                5. The new order may NEVER conflict with the natural flow between the blocks, so make sure that when reading the blocks in your new order it feels like a natural flow of text.
                6. You are not allowed to change the text in the blocks.
                7. Make sure that your the UIDs of the blocks do exist in "Block list".
                8. You can find the UID of a block in _metadata.
                    
                Please provide as your answer:
                1. Block order: consisting of the UIDs of the blocks
                2. A brief explanation of why you chose this order, focused on the main improvements.

                Information you can use:
                Block list: {state['generic_page']["blocks"]}.
                Customer information: Industry: IT Cloud computing.
        """)

        print("Personalized order: " + str(response))

        # Update the block order of the page to the generated order
        current_block_list = state["personalized_page"]["blocks"]
        updated_block_list = []
        for uid in response.block_order:
            for block in current_block_list:
                if block["block"]["_metadata"]["uid"] == uid:
                    updated_block_list.append(block)
                    break

        state["personalized_page"]["blocks"] = updated_block_list

        # Remove step from personalization queue
        state["personalization_queue"].pop(0)
        state["is_retry_step"] = False
        return state

    except Exception as e:
        if state["is_retry_step"]:
            print(f"An error occurred when personalizing the order of the elements of a page: {str(e)}")
            state["personalized_page"] = {"Error": str(e)}
            state["personalization_queue"] = []
        else:
            print(f"An error occurred when personalizing the order of the elements of a page, trying again. Error message: {str(e)}")
            state["is_retry_step"] = True
        return state

def save_personalized_page_node (state:AgentState):
    """Save the personalized page in the database."""
    print("Saving personalized page...")

    # Prepare database connection
    database = config["db"]["client"][config["db"]["db_name"]]
    collection = database["pages"]

    try:
        generated_page = state["personalized_page"]

        # Save personalized page in the database
        if collection.count_documents({'title': generated_page["title"]}) == 0:
            response = collection.insert_one(generated_page)
            print(f"successfully saved personalized page in database with ID: {response.inserted_id}")
        else:
            # Replace the page if it already exists
            response = collection.replace_one(
                {'title': generated_page['title']},
                generated_page
            )
            print(f"successfully updated existing personalized page in database")

        # Remove step from personalization queue
        state["personalization_queue"].pop(0)
        return state

    except Exception as e:
        if state["is_retry_step"]:
            print(f"An error occurred while saving the personalized page in the database: {str(e)}")
            state["personalization_queue"] = []
        else:
            print(f"An error occurred while saving the personalized page in the database, trying again. Error message: {str(e)}")
            state["is_retry_step"] = True
        return state
# endregion

# Create graph
graph = StateGraph(AgentState)
graph.add_node("FetchData", fetch_data_node)
graph.add_node("PersTexts", personalize_texts_node)
graph.add_node("PersImages", personalize_images_node)
graph.add_node("PersElmtOrder", personalize_element_order_node)
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
        "p_order": "PersElmtOrder",
        "save": "SavePersPage",
        "end": END
    }
)
graph.add_edge("PersTexts", "Router")
graph.add_edge("PersImages", "Router")
graph.add_edge("PersElmtOrder", "Router")
graph.add_edge("SavePersPage", END)
personalizationAgent = graph.compile()

# Run agent
result = personalizationAgent.invoke({"content_type_uid": "page"})

