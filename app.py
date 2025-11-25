from typing import TypedDict, List
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from ddgs import DDGS
from langchain.tools import tool
from langchain.agents import create_agent
from langgraph.graph import StateGraph, START, END
from pymongo import MongoClient
from pydantic import BaseModel, Field
from flask import Flask, request
import os
import requests
import prompts


# region Initialization
def initialize_config():
    load_dotenv()

    llm_config = ChatOpenAI(
        model=os.getenv("BONZAI_MODEL"),
        api_key=os.getenv("BONZAI_API_KEY"),
        base_url=os.getenv("BONZAI_URL"),
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
    print("Connected LLM Router: " + config_variables["llm"].openai_api_base + " with model: " + config_variables["llm"].model_name)

    try:
        config_variables["db"]["client"].admin.command('ping')
        print("Connected DB: " + str(config_variables["db"]["client"]))
    except Exception as e:
        print(f"Couldn't connect to MongoDB: {e}")

    return config_variables

config = initialize_config()
# endregion

# region Agentic tools
@tool
def search_web(item_to_search: str) -> list:
    """Search a specific company on the internet."""
    print(f"Searching the web for '{item_to_search}'...")

    with DDGS() as ddgs:
        results = ddgs.text(
            item_to_search,
            region='uk',
            language='en',
            safesearch='moderate',
            max_results=3
        )
        for item in list(results):
            print("Search result: " + str(item))
        return list(results)

tools = [search_web]
# endregion

# region Langgraph nodes
class AgentState(TypedDict):
    content_type_uid: str
    customer_uid: str
    customer_organization: str
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
    # Create ContentStack API calls (CMS)
    cms_headers = {
        "api_key": config["cms"]["api_key"],
        "access_token": config["cms"]["delivery_token"],
        "Content-Type": "application/json"
    }

    cms_params = {
        "environment": config["cms"]["environment"],
        "include[]": "header_reference"
    }

    retrieve_pages_url = f"{config['cms']['base_url']}/content_types/{state['content_type_uid']}/entries"
    retrieve_assets_url = f"{config['cms']['base_url']}/assets"

    # Setup personalization queue and extract page to personalize
    state["personalization_queue"] = ["text", "image", "order", "save"]  # TODO: This will be replaced by an agent deciding the steps to execute

    # Retrieve pages from Content Management System
    try:
        response = requests.get(retrieve_pages_url, headers=cms_headers, params=cms_params)
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
        if page["title"] == "Our Services":
            state["personalized_page"] = page  # TODO: This will be replaced by an agent deciding what pages to personalize

    state["is_retry_step"] = False

    # Retrieve assets from Content Management System
    try:
        response = requests.get(retrieve_assets_url, headers=cms_headers, params=cms_params)
        response.raise_for_status()
        asset_list = response.json()

        state["asset_list"] = asset_list
        print("Retrieved assets from CMS")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while retrieving assets from CMS: {str(e)}")
        state["personalization_queue"] = []
        return state

    # Create Lytics API calls (CDP)
    try:
        customer_information_headers = {
            "authorization": config["cdp"]["api_key"]
        }

        customer_information_url = f"{config['cdp']['base_url']}/entity/user/_uid/{state['customer_uid']}"

        # Retrieve customer information from Customer Data Platform
        try:
            response = requests.get(customer_information_url, headers=customer_information_headers)
            response.raise_for_status()
            customer_profile = response.json()

            state["customer_profile"] = customer_profile
            print("Retrieved customer information from CDP")
            return state

        except requests.exceptions.RequestException as e:
            print(f"An error occurred while retrieving customer information from CDP: {str(e)}")
            state["personalization_queue"] = []
            return state
    except:
        return state


def analyze_company_node(state: AgentState):
    """Analyze the email domain of the user, to find information about the company and industry the user works in."""

    try:
        email_domain_to_analyze = state["customer_profile"]["data"]["email_domain"]
        is_email_analysis = True

    except:
        if state["customer_organization"] != None:
            is_email_analysis = False
        else:
            state["personalization_queue"] = []
            print(f"An error occurred when analyzing the email domain: user has no email domain information or user_id is incorrect")
            state["personalized_page"] = {"Error": "user has no email domain information or user_id is incorrect"}
            return state


    if is_email_analysis:
        # Check if the domain is private
        if email_domain_to_analyze == "gmail.com" or email_domain_to_analyze == "outlook.com":
            print(f"Email address is not a business email, therefor domain can't be analyzed")
            state["personalized_page"] = {"Error": "Email address is not a business email"}
            state["personalization_queue"] = []
            return state
        else:
            print (f"Analyzing email domain {email_domain_to_analyze}...")
    else:
        print(f"Analyzing organization from IP: {state['customer_organization']}")

    # Create agent with structured output
    class CompanyInformation(BaseModel):
        company_size: int
        industry: str
        country: str
        steps_executed: str

    company_analyzer_agent = create_agent(
        model = config["llm"],
        tools = tools,
        response_format = CompanyInformation
    )

    try:
        if is_email_analysis:
            response = company_analyzer_agent.invoke({"messages": [("user", prompts.company_analysis.format(company=email_domain_to_analyze))]})
        else:
            response = company_analyzer_agent.invoke({"messages": [("user", prompts.company_analysis.format(company=state["customer_organization"]))]})
        response = response["structured_response"]

        print("Analysis result: " + str(response))

        if response.industry != "not found":
            customer_information = {"industry": response.industry}

            if response.company_size != -1:
                customer_information["company_size"] = response.company_size
            if response.country != "not found":
                customer_information["country"] = response.country

            state["customer_information"] = customer_information
            print(state["customer_information"])
            return state
        else:
            if state["is_retry_step"]:
                state["personalization_queue"] = []
                if is_email_analysis:
                    print(f"Unable to find the industry of the email domain: {email_domain_to_analyze}")
                    state["personalized_page"] = {"Error": f"Unable to find the industry of the email domain: {email_domain_to_analyze}"}
                else:
                    print(f"Unable to find the industry of the company: {state['customer_organization']}")
                    state["personalized_page"] = {"Error": f"Unable to find the industry of the company: {state['customer_organization']}"}
            else:
                if is_email_analysis:
                    print(f"Unable to find the industry of the email domain: {email_domain_to_analyze}, trying again.")
                else:
                    print(f"Unable to find the industry of the company: {state['customer_organization']}")
                state["is_retry_step"] = True
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
            generated_text = config["llm"].with_structured_output(GeneratedText).invoke(prompts.personalize_texts.format(
                customer_industry = state["customer_information"]["industry"],
                customer_information = state["customer_information"],
                block_to_personalize = block,
                block_list = state["personalized_page"]["blocks"]))

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
        titles: List[str] = Field(description="The list with the titles of the chosen images.")
        block_uids: List[str]  = Field(description="The list with the UIDs of the blocks where the chosen images should be put.")
        explanation: List[str]  = Field(description="The explanation of why you chose these images and why you placed them in the blocks you chose.")

    try:
        response = config["llm"].with_structured_output(Image).invoke(prompts.personalize_images.format(
            block_list = state["personalized_page"]["blocks"],
            image_list = stripped_asset_list,
            customer_information = state["customer_information"]))

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
        block_order: List[str] = Field(description="The order of the blocks by page uid.")
        explanation: str = Field(description="The reason why this order is better.")

    # Create stripped block list without the first element (first element should always be on top of page)
    stripped_block_list = state["personalized_page"]["blocks"]
    stripped_block = stripped_block_list[0]
    del stripped_block_list[0]

    # Generate personalized text
    try:
        response = config["llm"].with_structured_output(GeneratedOrder).invoke(prompts.personalize_element_order.format(
            block_list = stripped_block_list,
            customer_information = state["customer_information"]
        ))

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
            print(f"Successfully updated existing personalized page in database")

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

# region Create graph
graph = StateGraph(AgentState)
graph.add_node("FetchData", fetch_data_node)
graph.add_node("AnalyzeCompany", analyze_company_node)
graph.add_node("PersTexts", personalize_texts_node)
graph.add_node("PersImages", personalize_images_node)
graph.add_node("PersElmtOrder", personalize_element_order_node)
graph.add_node("Router", personalization_router_node)
graph.add_node("SavePersPage", save_personalized_page_node)

graph.add_edge(START, "FetchData")
graph.add_edge("FetchData", "AnalyzeCompany")
graph.add_edge("AnalyzeCompany", "Router")
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
# endregion

# Run Flask server to check for incoming personalization requests
app = Flask(__name__)

@app.route("/personalize", methods=["POST"])
def personalization_request():
    # Retrieve payload and check request
    payload = request.get_json()

    if "customer_organization" in payload or "customer_uid" in payload:
        payload["content_type_uid"] = "page"

        # Call the agent and check for errors when done
        result = personalizationAgent.invoke(payload)
        if "Error" in result["personalized_page"]:
            return {"Internal Server Error": result["personalized_page"]["Error"]}, 500
        else:
            return {"Success": "The personalization process has been completed successfully."}, 200
    else:
        return {"Bad Request Error": "No customer_id or customer_organization in payload."}, 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)