from copy import deepcopy
from typing import TypedDict, List, Literal
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from ddgs import DDGS
from langchain.tools import tool
from langchain.agents import create_agent
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from pymongo import MongoClient
from pydantic import BaseModel, Field
from flask import Flask, request
from flask_httpauth import HTTPBasicAuth
from flask_talisman import Talisman
import os
import requests
import prompts
import asyncio


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

    if os.getenv("ENVIRONMENT") == "development":
        url = os.getenv("MONGODB_DEV_URL")
    else:
        url = os.getenv("MONGODB_URL")

    db_config = {
        "client": MongoClient(url),
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
        return list(results)

tools = [search_web]
# endregion

# region Langgraph nodes
class PreparationState(TypedDict):
    customer_uid: str
    customer_organization: str
    customer_profile: dict
    customer_information: dict
    page_list: dict
    asset_list: dict
    pages_to_personalize: list
    personalized_pages: list
    error_occurred: bool
    error_message: str
    is_retry_step: bool

class PersonalizationProcessState(TypedDict):
    customer_information: dict
    page_to_personalize: dict
    asset_list: dict
    personalization_queue: list
    is_retry_step: bool


def fetch_data_node(state: PreparationState):
    """Retrieve the following data from their respective API endpoints:
        - CMS pages
        - CMS assets
        - CDP customer information
    """
    # Initialize error variables
    state["error_occurred"] = False
    state["is_retry_step"] = False

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

    retrieve_pages_url = f"{config['cms']['base_url']}/content_types/page/entries"
    retrieve_assets_url = f"{config['cms']['base_url']}/assets"

    # Retrieve pages from Content Management System
    try:
        response = requests.get(retrieve_pages_url, headers=cms_headers, params=cms_params)
        response.raise_for_status()
        page_list = response.json()

        state["page_list"] = page_list
        print("Retrieved pages from CMS")
    except requests.exceptions.RequestException as e:
        state["error_message"] = f"An error occurred while retrieving pages from CMS: {str(e)}"
        handle_error_preparation_process(state, "FetchData")
        return state

    # Retrieve assets from Content Management System
    try:
        response = requests.get(retrieve_assets_url, headers=cms_headers, params=cms_params)
        response.raise_for_status()
        asset_list = response.json()

        state["asset_list"] = asset_list
        print("Retrieved assets from CMS")
    except requests.exceptions.RequestException as e:
        state["error_message"] = f"An error occurred while retrieving assets from CMS: {str(e)}"
        handle_error_preparation_process(state, "FetchData")
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
            state["error_message"] = f"An error occurred while retrieving customer information from CDP: {str(e)}"
            handle_error_preparation_process(state, "FetchData")
            return state
    except:
        return state


def analyze_company_node(state: PreparationState):
    """Analyze the email domain or company name of the user, to find information about the company and industry the user works in."""
    # If an error has occured in one of the previous steps, quit the process
    if state["error_occurred"]:
        return state

    try:
        email_domain_to_analyze = state["customer_profile"]["data"]["email_domain"]
        is_email_analysis = True

    except:
        try:
            if state["customer_organization"] is not None:
                is_email_analysis = False
        except:
            state["error_message"] = f"An error occurred when analyzing the email domain: user has no IP organization or known email, personalization is not therefor not possible"
            print(state["error_message"])
            state["error_occurred"] = True
            return state


    if is_email_analysis:
        # Check if the domain is private
        if email_domain_to_analyze == "gmail.com" or email_domain_to_analyze == "outlook.com":
            state["error_message"] = f"Email address is not a business email, therefor domain can't be analyzed"
            print(f"Email address is not a business email, therefor domain can't be analyzed")
            state["error_occurred"] = True
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
            customer_information = {"industry": response.industry, "customer_uid": state["customer_uid"]}

            if response.company_size != -1:
                customer_information["company_size"] = response.company_size
            if response.country != "not found":
                customer_information["country"] = response.country

            state["customer_information"] = customer_information
            return state
        else:
            if is_email_analysis:
                state["error_message"] = f"Unable to find the industry of the email domain: {email_domain_to_analyze}"
                handle_error_preparation_process(state, "analyzeCompany")
            else:
                state["error_message"] = f"Unable to find the industry of the company: {state['customer_organization']}"
                handle_error_preparation_process(state, "analyzeCompany")
                analyze_company_node(state)
            return state


    except Exception as e:
        state["error_message"] = f"An error occurred when analyzing the email domain: {str(e)}"
        handle_error_preparation_process(state, "analyzeCompany")
        return state


def decide_pages_to_personalize_node(state: PreparationState):
    """Investigate the website pages and determine what pages (and components) could benefit from personalization."""
    # If an error has occured in one of the previous steps, quit the process
    if (state["error_occurred"]):
        return state

    print("Deciding what pages to personalize...")

    # Create agent with structured output
    class PersonalizationRequired(BaseModel):
        pages_that_require_personalization: List[str]
        explanation: str

    try:
        # Decide what pages could benefit from personalization
        response = config["llm"].with_structured_output(PersonalizationRequired).invoke(
                prompts.decide_pages_to_personalize.format(
                    customer_industry=state["customer_information"]["industry"],
                    pages=state["page_list"]["entries"]))

        # Retrieve page information connected to the title
        pages_to_personalize = []
        titles_of_pages = []
        for page_title_to_personalize in response.pages_that_require_personalization:
            for page in state["page_list"]["entries"]:
                if page_title_to_personalize == page["title"]:
                    if page["blocks"] != []:
                        pages_to_personalize.append(page)
                        titles_of_pages.append(page["title"])
                    else:
                        print("Page " + page["title"] + " was chosen to personalize, but it has no blocks what can be personalized. Skipping...")

        print("The pages to personalize have been chosen: " + str(titles_of_pages))
        state["pages_to_personalize"] = pages_to_personalize
        return state

    except Exception as e:
        state["error_message"] = f"Agent was unable to decide what pages should be personalized: {str(e)}"
        handle_error_preparation_process(state, "DecidePagesToPers")
        return state


async def parallel_processing_node(state:PreparationState):
    """This node starts the personalization process of each selected page in parallel."""
    # If an error has occured in one of the previous steps, quit the process
    if state["error_occurred"]:
        return state

    base_parameters = {
        "customer_information": state["customer_information"],
        "asset_list": state["asset_list"],
        "is_retry_step": False
    }

    tasks = []
    for page in state["pages_to_personalize"]:
        # Create a deepcopy of the base parameters and add the page that needs to be personalized
        request_parameters = deepcopy(base_parameters)
        request_parameters["page_to_personalize"] =  page

        # Start personalization process for page
        print("Starting personalization process for page: " + page["title"])
        task = personalization_graph.ainvoke(request_parameters)
        tasks.append(task)

    results = await asyncio.gather(*tasks)
    state["personalized_pages"] = results

    for page in results:
        if "Error" in page["page_to_personalize"]:
            state["error_message"] = page["page_to_personalize"].get("Error")
            state["error_occurred"] = True
            break

    if state["error_occurred"]:
        print("Website personalization failed.")
    else:
        print("Website personalization completed successfully.")

    return state


def decide_components_to_personalize_node(state: PersonalizationProcessState):
    """Investigate the page to personalize and determine what components could benefit from personalization."""
    # Create agent with structured output
    class PersonalizationSteps(BaseModel):
        personalization_list: List[str]
        explanation: str

    try:
        # Decide what components could benefit from personalization
        response = config["llm"].with_structured_output(PersonalizationSteps).invoke(
                prompts.decide_components_to_personalize.format(
                    customer_industry=state["customer_information"]["industry"],
                    page_blocks=state["page_to_personalize"]["blocks"]))

        # Create personalization_queue
        if response.personalization_list != []:
            state["personalization_queue"] = response.personalization_list
            state["personalization_queue"].append("save")
            print (f"[{state['page_to_personalize']['title']}] Personalization steps to execute have been chosen: {state['personalization_queue']}")
        else:
            handle_error_personalization_process(state, "Error: Agent chose no components to personalize")

        return state

    except Exception as e:
        handle_error_personalization_process(state, f"Agent was unable to decide what components should be personalized: {str(e)}")
        return state


def personalization_router_node(state: PersonalizationProcessState) -> Command[Literal["PersTexts", "PersImages", "PersElmtOrder", "SavePersPage", "__end__"]]:
    """Routes to the next node in the queue."""
    if state["personalization_queue"] != []:
        match state["personalization_queue"][0]:
            case "text":
                goto = "PersTexts"
            case "image":
                goto = "PersImages"
            case "order":
                goto = "PersElmtOrder"
            case "save":
                goto = "SavePersPage"

        return Command(goto=goto)

    return Command(goto="__end__")


async def personalize_texts_node(state: PersonalizationProcessState):
    """Personalize text(s): generate a tailored text based on the content of the generic page and the customer's background."""
    try:
        block_list = state["page_to_personalize"]["blocks"]
        tasks = []

        # Personalize all blocks at the same time
        for block in block_list:
            task = personalize_text(state["customer_information"], block_list, block)
            tasks.append(task)

        personalized_texts = await asyncio.gather(*tasks)

        # Update the pages with the generated content
        for i, text in enumerate(personalized_texts):
            block_list[i]["block"]["copy"] = text.copytext
            block_list[i]["block"]["title"] = text.title

        # Update state with the updated block list
        state["page_to_personalize"]["blocks"] = block_list

        # Remove step from personalization queue
        state["personalization_queue"].pop(0)
        state["is_retry_step"] = False

        print(f"[{state['page_to_personalize']['title']}] Text personalization completed.")
        return state

    except Exception as e:
        handle_error_personalization_process(state, f"An error occurred when personalizing the text of page: {str(e)}")
        return state


async def personalize_text(customer_information, block_list, block_to_personalize):
    """Async function that is called to personalize all texts at the same time."""
    # Output structure
    class GeneratedText(BaseModel):
        title: str = Field(description="The generated title.")
        copytext: str = Field(description="The generated copy text.")
        explanation: str = Field(description="The reason why this text is better.")

    # Generate the text
    return await config["llm"].with_structured_output(GeneratedText).ainvoke(prompts.personalize_texts.format(
        customer_industry=customer_information["industry"],
        customer_information=customer_information,
        block_to_personalize=block_to_personalize,
        block_list=block_list))


def personalize_images_node(state: PersonalizationProcessState):
    """Personalize image(s): choose the best fitting image for the content of the page and the customer's background."""
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
            block_list = state["page_to_personalize"]["blocks"],
            image_list = stripped_asset_list,
            customer_information = state["customer_information"]))

        print(f"[{state['page_to_personalize']['title']}] Personalized images: " + str(response))

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
            for block in state["page_to_personalize"]["blocks"]:
                if block["block"]["_metadata"]["uid"] == uid:
                    block_details.append(block)
                    break

        # Update chosen blocks with new images
        if len(block_details) != 0:
            for index, block in enumerate(block_details):
                block["block"]["image"] = image_details[index]
        else:
            handle_error_personalization_process(state, f"An error occurred when personalizing the image of page: one or more of the chosen images ({response.titles}) or blocks ({response.block_uids}) do not exist.")
            return state

        # Remove step from personalization queue
        state["personalization_queue"].pop(0)
        state["is_retry_step"] = False
        return state

    except Exception as e:
        handle_error_personalization_process(state, f"An error occurred when personalizing the image of page: {str(e)}")
        return state


def personalize_element_order_node(state: PersonalizationProcessState):
    """Change the order of blocks on a page: change the blocks based on the content of the generic page and the customer's background."""
    # Define output structure
    class GeneratedOrder(BaseModel):
        block_order: List[str] = Field(description="The order of the blocks by page uid.")
        explanation: str = Field(description="The reason why this order is better.")

    # Create stripped block list without the first element (first element should always be on top of page)
    stripped_block = state["page_to_personalize"]["blocks"][0]
    stripped_block_list = state["page_to_personalize"]["blocks"][1:]

    # Generate personalized text
    try:
        response = config["llm"].with_structured_output(GeneratedOrder).invoke(prompts.personalize_element_order.format(
            block_list = stripped_block_list,
            customer_information = state["customer_information"]
        ))

        print(f"[{state['page_to_personalize']['title']}] Personalized order: " + str(response))

        # Update the block order of the page to the generated order
        updated_block_list = [stripped_block]

        if response.block_order != []:
            for uid in response.block_order:
                for block in stripped_block_list:
                    if block["block"]["_metadata"]["uid"] == uid:
                        updated_block_list.append(block)
                        break

            state["page_to_personalize"]["blocks"] = updated_block_list
        else:
            handle_error_personalization_process(state, f"An error occurred when personalizing the order of the elements of page: No block uids have been returned by the agent")
            return state

        # Remove step from personalization queue
        state["personalization_queue"].pop(0)
        state["is_retry_step"] = False
        return state

    except Exception as e:
        handle_error_personalization_process(state, f"An error occurred when personalizing the order of the elements of page: {str(e)}")
        return state


def save_personalized_page_node(state: PersonalizationProcessState):
    """Save the personalized page in the database."""
    # Prepare database connection
    database = config["db"]["client"][config["db"]["db_name"]]
    collection = database["pages"]

    try:
        # Prepare page by adding the customer uid
        state["page_to_personalize"]["customer_uid"] = state["customer_information"]["customer_uid"]
        generated_page = state["page_to_personalize"]


        # Save personalized page in the database
        if collection.count_documents({'title': generated_page["title"]}) == 0:
            response = collection.insert_one(generated_page)
            print(f"[{state['page_to_personalize']['title']}] Successfully saved the new personalized page in database (ID: {response.inserted_id})")
        else:
            # Replace the page if it already exists
            response = collection.replace_one(
                {'title': generated_page['title']},
                generated_page
            )
            print(f"[{state['page_to_personalize']['title']}] Successfully updated an existing personalized page in database")

        # Remove step from personalization queue
        state["personalization_queue"].pop(0)
        return state

    except Exception as e:
        handle_error_personalization_process(state, f"An error occurred while saving the personalized page in the database: {str(e)}")
        return state


def handle_error_personalization_process(state: PersonalizationProcessState, error_message:str):
    """Handle an error during the personalization process."""
    # If it is a retried step return an error
    if state["is_retry_step"]:
        state["personalization_queue"] = []
        print(
            f"[{state['page_to_personalize']['title']}] {error_message}")
        state["page_to_personalize"] = {"Error": error_message}
    # If it is a first error try to execute the node again
    else:
        print(
            f"[{state['page_to_personalize']['title']}] {error_message}. Trying again...")
        state["is_retry_step"] = True


def handle_error_preparation_process(state: PreparationState, node: str):
    """Handle an error during the preparation process."""
    # If it is a retried step or an error occurred during the fetch data node, return the error_occurred to stop the program
    if state["is_retry_step"] or node == "FetchData":
        print(state["error_message"])
        state["error_occurred"] = True
    # If it is a first error of one of the other nodes, try again
    else:
        print(state["error_message"] + ". Trying again...")
        state["is_retry_step"] = True

        match node:
            case "analyzeCompany":
                analyze_company_node(state)
            case "DecidePagesToPers":
                decide_pages_to_personalize_node(state)



# endregion

# region Create graphs
# GRAPH 1: PREPARATION FLOW (Sequential)
prepFlow = StateGraph(PreparationState)
prepFlow.add_node("FetchData", fetch_data_node)
prepFlow.add_node("AnalyzeCompany", analyze_company_node)
prepFlow.add_node("DecidePagesToPers", decide_pages_to_personalize_node)
prepFlow.add_node("ParallelProcessing", parallel_processing_node)

prepFlow.add_edge(START, "FetchData")
prepFlow.add_edge("FetchData", "AnalyzeCompany")
prepFlow.add_edge("AnalyzeCompany", "DecidePagesToPers")
prepFlow.add_edge("DecidePagesToPers", "ParallelProcessing")
prepFlow.add_edge("ParallelProcessing", END)
preparation_graph = prepFlow.compile()

# GRAPH 2: PERSONALIZATION PROCESS
persFlow = StateGraph(PersonalizationProcessState)

persFlow.add_node("DecideComponentsToPers", decide_components_to_personalize_node)
persFlow.add_node("Router", personalization_router_node)
persFlow.add_node("PersTexts", personalize_texts_node)
persFlow.add_node("PersImages", personalize_images_node)
persFlow.add_node("PersElmtOrder", personalize_element_order_node)
persFlow.add_node("SavePersPage", save_personalized_page_node)

# This graph has no edges from the router to other nodes, because it routes to different nodes depending on the chosen personalization steps
persFlow.add_edge(START, "DecideComponentsToPers")
persFlow.add_edge("DecideComponentsToPers", "Router")

persFlow.add_edge("PersTexts", "Router")
persFlow.add_edge("PersImages", "Router")
persFlow.add_edge("PersElmtOrder", "Router")
persFlow.add_edge("SavePersPage", END)
personalization_graph = persFlow.compile()
# endregion

# Run Flask server to check for incoming personalization requests and personalized page retrievals
app = Flask(__name__)
Talisman(app, force_https=True)
auth = HTTPBasicAuth()

# Authentication handler
@auth.verify_password
def verify_auth(username, password):
    if username == os.getenv('AUTH_USERNAME') and password == os.getenv('AUTH_PASSWORD'):
        return True
    return False

@app.route('/personalize', methods=['POST'])
@auth.login_required
async def personalization_request():
    # Retrieve payload and check request
    payload = request.get_json()

    if "customer_organization" in payload or "customer_uid" in payload:
        # Call the agent and check for errors when done
        result = await preparation_graph.ainvoke(payload)
        if result["error_occurred"]:
            return {"Internal Server Error": str(result["error_message"])}, 500
        else:
            return {"Success": "The personalization process has been completed successfully."}, 200
    else:
        return {"Bad Request Error": "No customer_id or customer_organization in payload."}, 400

@app.route('/personalize/<customer_uid>/<slug>', methods=['GET'])
@auth.login_required
def retrieve_personalized_pages(customer_uid: str, slug: str):
    if customer_uid is None or slug is None:
        return {"Bad Request Error": "Customer_uid or slug is missing."}, 400
    else:
        try:
            database = config["db"]["client"][config["db"]["db_name"]]
            collection = database["pages"]
            slug = "/" + slug
            cursor = collection.find({"customer_uid": customer_uid, "url": slug}, {"_id": 0})
            personalized_pages = list(cursor)

            if len(personalized_pages) > 0:
                return personalized_pages, 200
            else:
                return {"Not Found Error": f"No personalized page for {slug} has been found for customer {customer_uid}."}, 404
        except Exception as e:
            return {"Internal Server Error": str(e)}, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, ssl_context='adhoc')