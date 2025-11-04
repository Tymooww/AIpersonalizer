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
        api_base=os.getenv("BONZAI_URL"),
        temperature=0.4
    )

    cms_config = {
        "base_url": os.getenv("CMS_BASE_URL"),
        "api_key": os.getenv("CMS_API_KEY"),
        "delivery_token": os.getenv("CMS_DELIVERY_TOKEN"),
        "management_token": os.getenv("CMS_MANAGEMENT_TOKEN"),
        "environment": os.getenv("CMS_ENVIRONMENT")
    }

    cdp_config = {
        "base_url": os.getenv("CDP_BASE_URL"),
        "api_key": os.getenv("CDP_API_KEY")
    }

    db_config = {
        "client": MongoClient(os.getenv("MONGODB_URL")),
        "db_name": os.getenv("MONGODB_DATABASE")
    }

    config_variables = {"llm": llm_config, "cms": cms_config, "db": db_config, "cdp": cdp_config}

    print("Connected CMS: " + config_variables["cms"]["base_url"])
    print("Connected CDP: " + config_variables["cdp"]["base_url"])
    print("Connected LLM Router: " + config_variables["llm"].api_base + " with model: " + config_variables["llm"].model)

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
    customer_uid: str
    customer_profile: dict
    customer_information: dict
    page_list: dict
    asset_list: dict
    personalized_page: dict
    personalization_queue: list
    is_retry_step: bool


def fetch_data_node(state: AgentState):
    """Retrieve the following data from their respective API endpoints:
        - CMS pages
        - CMS assets
        - CDP customer information
    """
    # Create ContentStack API calls
    contentstack_headers = {
        "api_key": config["cms"]["api_key"],
        "access_token": config["cms"]["delivery_token"],
        "Content-Type": "application/json"
    }

    contentstack_params = {
        "environment": config["cms"]["environment"],
        "include[]": "header_reference"
    }

    retrieve_pages_url = f"{config['cms']['base_url']}/content_types/{state['content_type_uid']}/entries"
    retrieve_assets_url = f"{config['cms']['base_url']}/assets"

    # Create Lytics API calls
    customer_information_headers = {
        "authorization": config["cdp"]["api_key"]
    }

    customer_information_url = f"{config['cdp']['base_url']}/entity/user/_uid/{state['customer_uid']}"

    # Setup personalization queue and extract page to personalize
    state["personalization_queue"] = ["text", "image", "order", "save"]  # TODO: This will be replaced by an agent deciding the steps to execute

    # Retrieve pages from ContentStack
    try:
        response = requests.get(retrieve_pages_url, headers=contentstack_headers, params=contentstack_params)
        response.raise_for_status()
        page_list = response.json()

        state["page_list"] = page_list
        print("Retrieved pages from CMS")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while retrieving pages from CMS: {str(e)}")
        state["personalization_queue"] = []
        return state

    # Extract the page to customize
    for page in state["page_list"]["entries"]:
        if page["title"] == "Our services":
            state["personalized_page"] = page  # TODO: This will be replaced by an agent deciding what pages to personalize

    state["is_retry_step"] = False

    # Retrieve assets from ContentStack
    try:
        response = requests.get(retrieve_assets_url, headers=contentstack_headers, params=contentstack_params)
        response.raise_for_status()
        asset_list = response.json()

        state["asset_list"] = asset_list
        print("Retrieved assets from CMS")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while retrieving assets from CMS: {str(e)}")
        state["personalization_queue"] = []
        return state

    # Retrieve customer information from Customer Data Platform
    try:
        response = requests.get(customer_information_url, headers=customer_information_headers)
        response.raise_for_status()
        customer_profile = response.json()

        print(customer_profile)

        state["customer_profile"] = customer_profile
        print("Retrieved customer information from CDP")
        return state

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while retrieving customer information from CDP: {str(e)}")
        state["personalization_queue"] = []
        return state

def analyze_email_domain_node(state: AgentState):
    """Analyze the email domain of the user, to find information about the company and industry the user works in."""

    # TODO: Check for private emails (outlook/gmail) and exit if it is private.

    email_domain_to_analyze = state["customer_profile"]["data"]["email_domain"]

    print (email_domain_to_analyze)

    class CompanyInformation(BaseModel):
        company_size: int
        industry: str
        country: str
        steps_executed: str


    try:
        response = config["llm"].with_structured_output(CompanyInformation).invoke(f"""
                        You are an expert in investigating the company behind email domains. 
                        
                        Your task: Analyse the {email_domain_to_analyze} domain and use the name to get an understanding of the organization the user works in. 

                        CRITICAL RULES:
                        1. You should find the size of the company/organization mentioned in the email domain, how many people work there?
                        2. You should find the industry or sector of the company/organization mentioned in the email domain.
                        3. You should search for the country the company/organization mentioned in the email domain is located in. If there are multiple locations, look for the biggest or most used one.
                        4. Don't hallucinate, make sure the information you provide does exist.
                        5. If you can't find the company size provide a -1 for company size or 'not found' for when you can't find the industry or country of the company.
                        
                        Please provide as your answer:
                        1. Company size: this should be an estimate of the amount of employees working at the company mentioned in the email domain.
                        2. Industry: the industry/sector of the company mentioned in the email domain.
                        3. Country: the country where the company mentioned in the email domain is located in.
                        4. Steps executed: provide the steps you have executed to get to your answers.

                        Information you can use:
                        Email domain: {email_domain_to_analyze}
                        """)

        print(response)

        # TODO: better error handling, should continue as long as industry has been found
        if response.company_size != -1 and response.industry != "not found" and response.country != "not found":

            state["customer_information"] = response

            print(state["customer_information"])
            return state

    except Exception as e:
        if state["is_retry_step"]:
            state["personalization_queue"] = []
            print(f"An error occurred when analyzing the email domain: {str(e)}")
            state["personalized_page"] = {"Error": str(e)}
        else:
            print(f"An error occurred when analyzing the email domain, trying again. Error message: {str(e)}")
            state["is_retry_step"] = True
        return state




def personalization_router_node(state: AgentState):
    """Router node for logging."""
    if len(state["personalization_queue"]) > 1:
        print(f"Next step: {state['personalization_queue'][0]}")
    else:
        print("Page personalization process finished.")

    return state


def determine_next_step(state: AgentState):
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


def personalize_texts_node(state: AgentState):
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

        for block in state["personalized_page"]["blocks"]:
            generated_text = config["llm"].with_structured_output(GeneratedText).invoke(f"""
                    You are an expert in personalized marketing.

                    Your task: Subtly adapt "Block to personalize" to resonate with someone in the {state['customer_information']['segment']} sector.

                    CRITICAL RULES:
                    1. DO NOT mention the industry name, words that are very obviously related to the industry (for agriculture cultivating for example), puns or use phrases like "tailored for", "designed for", "specialized in [industry]" and don't use the same or similar wordings in every block!
                    2. DO personalize by:
                    - Emphasizing relevant challenges specific to this industry
                    - Highlighting services that solve their unique problems
                    - Using examples and scenarios they recognize
                    - Adjusting tone and focus to match their priorities
   
                    3. Example (use for reference, don't use explicitly):
                    TOO EXPLICIT: "Investment management for IT professionals in the tech sector"
                    TOO GENERIC: "Investment management for professionals"
                    JUST RIGHT: "Investment management for professionals managing equity compensation and frequent career transitions"

                    4. Stay conservative:
                    - Only adjust emphasis, examples, and specific pain points
                    - Never invent new products or services
                    - Maintain the professional tone

                    5. Content preservation:
                    - Sell the SAME products/services mentioned in the original
                    - Don't add features that weren't there
                    - Improve clarity and relevance, not scope

                    6. Output in HTML format

                    INDUSTRY CONTEXT (use implicitly, DON'T mention explicitly):
                    {state['customer_information']}

                    ---

                    Block to personalize: {block}
                    Other blocks (for reference): {state['personalized_page']['blocks']}

                    ---

                    Provide:
                    1. Title: The personalized title (no industry name!)
                    2. Copytext: The personalized copy (HTML)
                    3. Explanation: Why these changes resonate with this audience (max 2 sentences).
            """)

            generated_titles.append(generated_text.title)
            generated_copy_texts.append(generated_text.copytext)

            print("Personalized text: " + str(generated_text))

        # Update the copy of the page to the generated text
        for block_id, _ in enumerate(state["personalized_page"]["blocks"]):
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


def personalize_images_node(state: AgentState):
    """Personalize image(s): choose the best fitting image for the content of the page and the customer's background."""
    print("Personalizing image...")

    # Strip assets information to essential data for LLM
    stripped_asset_list = []
    for asset in state["asset_list"]["assets"]:
        stripped_asset = {"title": asset.get("title", "No title found"), "filename": asset.get("filename"),
                          "description": asset.get("description", "No description found"),
                          "tags": asset.get("tags", [])}
        stripped_asset_list.append(stripped_asset)

    # Define output structure
    class Image(BaseModel):
        titles: list = Field(description="The list with the titles of the chosen images.")
        block_uids: list = Field(
            description="The list with the UIDs of the blocks where the chosen images should be put.")
        explanation: str = Field(
            description="The explanation of why you chose these images and why you placed them in the blocks you chose.")

    try:
        response = config["llm"].with_structured_output(Image).invoke(f"""
                You are an expert in personalized marketing.
                Your task: use "Customer information" and "Image list" to find the best fitting image(s) for the blocks in "Block list". 
                Important: 
                1. Analyze all images in "Image list" to find fitting images.
                2. You can analyze images by looking at their title, filename, description and tags.
                3. The image you choose must fit the title and/or copy of the block and should also fit with the customer's interests.
                4. Images already present in blocks can also be changed, but it is not mandatory
                5. It is mandatory to have at least TWO blocks with an image, more blocks with an image are allowed. less is not allowed, so at least TWO
                6. A block can only have one image.
                7. Every image needs to have a block to be displayed in, so there should be as many block UIDs as titles
                8. You can find the UID of a block in _metadata.
                9. Make sure that your chosen title(s) exist in "Image list", don't invent new titles but copy them over.
                10. Make sure that your chosen UID(s) exist in "Block list", don't invent new UIDs but copy them over.
                    
                Please provide as your answer:
                1. Title: this title is from the image you want to place.
                2. Block UID: this UID is from the block you want to place the image.
                3. A brief explanation of why you chose these images and why you placed them in the blocks you chose, focused on the main improvements.

                Information you can use:
                Block list: {state['personalized_page']["blocks"]}.
                Image list: {stripped_asset_list}.
                Customer information: {state['customer_information']}.
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
            for block in state["personalized_page"]["blocks"]:
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
                print(
                    f"An error occurred when personalizing the image of a page: one or more of the chosen images ({response.titles}) or blocks ({response.block_uids})do not exist.")
                state["personalized_page"] = {
                    "Error": f"Error: one or more of the chosen images ({response.titles}) or blocks ({response.block_uids}) do not exist."}
            else:
                print(
                    f"One or more of the chosen images ({response.titles}) or blocks ({response.block_uids}) do not exist, trying again.")
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


def personalize_element_order_node(state: AgentState):
    """Change the order of blocks on a page: change the blocks based on the content of the generic page and the customer's background."""
    print("Personalizing order of elements...")

    # Define output structure
    class GeneratedOrder(BaseModel):
        block_order: list = Field(description="The order of the blocks by page uid.")
        explanation: str = Field(description="The reason why this order is better.")

    # Create stripped block list without the first element (first element should always be on top of page)
    stripped_block_list = state["personalized_page"]["blocks"]
    stripped_block = stripped_block_list[0]
    del stripped_block_list[0]

    # Generate personalized text
    try:
        response = config["llm"].with_structured_output(GeneratedOrder).invoke(f"""
                You are an expert in personalized marketing.
                Your task: use "Customer information" and "Block list" to create a personalized order for the blocks of the provided page.
                Important: 
                1. Use "Customer information" to decide what blocks are the most relevant for the customer.
                2. Place the most relevant blocks first in the order. And make sure to change the place of at least one block in a different place.
                3. All blocks need to be in the list, so the amount of blocks in the Block list should be the same as the amount of UIDs given in the answer.
                4. The new order may NEVER conflict with the natural flow between the blocks, so make sure that when reading the blocks in your new order it feels like a natural flow of text.
                5. You are not allowed to change the text in the blocks.
                6. Make sure that your the UIDs of the blocks do exist in "Block list".
                7. You can find the UID of a block in _metadata.
                    
                Please provide as your answer:
                1. Block order: consisting of the UIDs of the blocks
                2. A brief explanation of why you chose this order, focused on the main improvements.

                Information you can use:
                Block list: {stripped_block_list}.
                Customer information: {state['customer_information']}.
        """)

        print("Personalized order: " + str(response))

        # Update the block order of the page to the generated order
        updated_block_list = [stripped_block]

        for uid in response.block_order:
            for block in stripped_block_list:
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
            print(
                f"An error occurred when personalizing the order of the elements of a page, trying again. Error message: {str(e)}")
            state["is_retry_step"] = True
        return state


def save_personalized_page_node(state: AgentState):
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
            print(
                f"An error occurred while saving the personalized page in the database, trying again. Error message: {str(e)}")
            state["is_retry_step"] = True
        return state


# endregion

# Create graph
graph = StateGraph(AgentState)
graph.add_node("FetchData", fetch_data_node)
graph.add_node("AnalyzeEmail", analyze_email_domain_node)
graph.add_node("PersTexts", personalize_texts_node)
graph.add_node("PersImages", personalize_images_node)
graph.add_node("PersElmtOrder", personalize_element_order_node)
graph.add_node("Router", personalization_router_node)
graph.add_node("SavePersPage", save_personalized_page_node)

graph.add_edge(START, "FetchData")
graph.add_edge("FetchData", "AnalyzeEmail")
graph.add_edge("AnalyzeEmail", "Router")
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

# Run agent for customer Johnny Hive
result = personalizationAgent.invoke({"content_type_uid": "page", "customer_uid": "fe15c42d-a7c1-4b23-ab74-cde617a9c494"})
