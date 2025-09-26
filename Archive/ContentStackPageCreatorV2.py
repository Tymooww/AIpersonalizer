from typing import TypedDict, Literal, Annotated
from langgraph.graph import StateGraph, END
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
import requests
import json
from dotenv import load_dotenv
import os

# 1. State Definition
class PersonalizationState(TypedDict):
    user_id: str
    messages: list
    pages_data: dict
    user_profile: dict
    selected_page: dict
    personalization_strategy: str
    execution_result: str
    current_step: str
    error_message: str


# 2. Configuration
load_dotenv()


class Config:
    def __init__(self):
        self.contentstack = {
            "base_url": os.getenv("CONTENTSTACK_URL"),
            "api_key": os.getenv("CONTENTSTACK_API_KEY"),
            "delivery_token": os.getenv("CONTENTSTACK_DELIVERY_TOKEN"),
            "management_token": os.getenv("CONTENTSTACK_MANAGEMENT_TOKEN"),
            "environment": os.getenv("CONTENTSTACK_ENVIRONMENT")
        }
        self.llm = ChatOllama(base_url='http://localhost:11434', model="mistral")


config = Config()


# 3. Node Functions
def fetch_pages_node(state: PersonalizationState):
    """Node 1: Fetch all available pages"""
    print(f"🔍 Step 1: Fetching pages from ContentStack...")

    try:
        headers = {
            "api_key": config.contentstack["api_key"],
            "access_token": config.contentstack["delivery_token"],
            "Content-Type": "application/json"
        }
        params = {"environment": config.contentstack["environment"]}
        url = f"https://{config.contentstack['base_url']}/v3/content_types/page/entries"

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        pages_data = response.json()

        print(f"✅ Found {len(pages_data.get('entries', []))} pages")

        return {
            "pages_data": pages_data,
            "current_step": "pages_fetched",
            "error_message": ""
        }

    except Exception as e:
        print(f"❌ Error fetching pages: {e}")
        return {
            "current_step": "error",
            "error_message": f"Failed to fetch pages: {e}"
        }


def analyze_pages_node(state: PersonalizationState):
    """Node 2: Analyze pages using AI agent"""
    print(f"🤖 Step 2: Analyzing pages with AI...")

    pages_data = state["pages_data"]

    @tool
    def analyze_page_opportunities(pages_json: str) -> str:
        """Analyze which pages have the best personalization opportunities"""
        pages = json.loads(pages_json)
        entries = pages.get('entries', [])

        analysis = []
        for entry in entries:
            title = entry.get('title', 'No title')
            tags = entry.get('tags', [])
            uid = entry.get('uid', '')

            # Simple scoring based on presence of personalizable elements
            score = 0
            if 'hero' in str(entry).lower(): score += 2
            if 'banner' in str(entry).lower(): score += 1
            if len(tags) > 0: score += 1
            if 'home' in title.lower(): score += 3  # Homepage is always good to personalize

            analysis.append({
                "title": title,
                "uid": uid,
                "tags": tags,
                "personalization_score": score
            })

        # Sort by personalization potential
        analysis.sort(key=lambda x: x['personalization_score'], reverse=True)
        return json.dumps(analysis[:3])  # Top 3 candidates

    # Create temporary agent for this analysis
    agent = create_react_agent(config.llm, [analyze_page_opportunities])

    try:
        result = agent.invoke({
            "messages": [
                ("user", f"Analyze these pages and recommend top 3 for personalization: {json.dumps(pages_data)}")]
        })

        # Extract the analysis from agent result
        analysis_text = result["messages"][-1].content

        print(f"✅ Analysis complete: {analysis_text[:100]}...")

        return {
            "selected_page": {"analysis": analysis_text},
            "current_step": "pages_analyzed"
        }

    except Exception as e:
        print(f"❌ Error in analysis: {e}")
        return {
            "current_step": "error",
            "error_message": f"Analysis failed: {e}"
        }


def fetch_user_profile_node(state: PersonalizationState):
    """Node 3: Fetch user profile (mock CDP call)"""
    print(f"👤 Step 3: Fetching user profile for {state['user_id']}...")

    # Mock CDP data - in real implementation this would be actual CDP API call
    mock_profiles = {
        "user123": {
            "interests": ["technology", "innovation", "products"],
            "segment": "premium_user",
            "lifetime_value": "high",
            "previous_purchases": ["laptop", "software"],
            "engagement_level": "high"
        },
        "user456": {
            "interests": ["design", "creativity"],
            "segment": "standard_user",
            "lifetime_value": "medium",
            "previous_purchases": [],
            "engagement_level": "medium"
        }
    }

    user_profile = mock_profiles.get(state["user_id"], {
        "interests": ["general"],
        "segment": "new_user",
        "lifetime_value": "unknown",
        "previous_purchases": [],
        "engagement_level": "low"
    })

    print(f"✅ Profile fetched: {user_profile['segment']}")

    return {
        "user_profile": user_profile,
        "current_step": "profile_fetched"
    }


def create_personalization_strategy_node(state: PersonalizationState):
    """Node 4: Create personalization strategy using AI"""
    print(f"🎯 Step 4: Creating personalization strategy...")

    @tool
    def create_strategy(user_profile_json: str, page_analysis: str) -> str:
        """Create personalization strategy based on user profile and page analysis"""
        user_profile = json.loads(user_profile_json)

        segment = user_profile.get('segment', 'unknown')
        interests = user_profile.get('interests', [])
        engagement = user_profile.get('engagement_level', 'unknown')

        strategies = []

        # Segment-based strategies
        if segment == "premium_user":
            strategies.append("Show premium features and exclusive content")
            strategies.append("Highlight advanced product capabilities")
        elif segment == "new_user":
            strategies.append("Focus on onboarding and getting started content")
            strategies.append("Show simple, easy-to-understand benefits")

        # Interest-based strategies
        if "technology" in interests:
            strategies.append("Emphasize technical specifications and innovation")
        if "design" in interests:
            strategies.append("Highlight visual design and user experience")

        # Engagement-based strategies
        if engagement == "high":
            strategies.append("Show detailed information and advanced features")
        else:
            strategies.append("Keep messaging simple and benefit-focused")

        final_strategy = " | ".join(strategies)
        return f"Personalization Strategy: {final_strategy}"

    agent = create_react_agent(config.llm, [create_strategy])

    try:
        result = agent.invoke({
            "messages": [("user", f"""Create a personalization strategy for this user and page:

            User Profile: {json.dumps(state['user_profile'])}
            Page Analysis: {state['selected_page']['analysis']}

            Consider the user's segment, interests, and engagement level.""")]
        })

        strategy = result["messages"][-1].content
        print(f"✅ Strategy created: {strategy[:100]}...")

        return {
            "personalization_strategy": strategy,
            "current_step": "strategy_created"
        }

    except Exception as e:
        print(f"❌ Error creating strategy: {e}")
        return {
            "current_step": "error",
            "error_message": f"Strategy creation failed: {e}"
        }


def execute_personalization_node(state: PersonalizationState):
    """Node 5: Execute the personalization"""
    print(f"⚡ Step 5: Executing personalization...")

    # In a real implementation, this would:
    # 1. Update ContentStack content via Management API
    # 2. Track the personalization event in CDP
    # 3. Set up A/B testing if needed

    strategy = state["personalization_strategy"]
    user_profile = state["user_profile"]

    # Mock execution result
    execution_result = {
        "status": "success",
        "personalized_elements": ["hero_banner", "call_to_action", "content_cards"],
        "strategy_applied": strategy,
        "user_segment": user_profile.get("segment"),
        "timestamp": "2024-01-01T12:00:00Z"
    }

    print(f"✅ Personalization executed successfully")

    return {
        "execution_result": json.dumps(execution_result, indent=2),
        "current_step": "completed"
    }


def error_node(state: PersonalizationState):
    """Handle errors"""
    print(f"❌ Error occurred: {state.get('error_message', 'Unknown error')}")
    return {
        "current_step": "failed",
        "execution_result": f"Process failed: {state.get('error_message', 'Unknown error')}"
    }


# 4. Routing Logic
def should_continue(state: PersonalizationState) -> Literal[
    "analyze", "fetch_profile", "create_strategy", "execute", "error", "end"]:
    """Determine the next step based on current state"""

    current_step = state.get("current_step", "")

    if current_step == "pages_fetched":
        return "analyze"
    elif current_step == "pages_analyzed":
        return "fetch_profile"
    elif current_step == "profile_fetched":
        return "create_strategy"
    elif current_step == "strategy_created":
        return "execute"
    elif current_step == "completed":
        return "end"
    elif current_step == "error" or current_step == "failed":
        return "error"
    else:
        return "error"


# 5. Build the Graph
def create_personalization_workflow():
    workflow = StateGraph(PersonalizationState)

    # Add nodes
    workflow.add_node("fetch_pages", fetch_pages_node)
    workflow.add_node("analyze", analyze_pages_node)
    workflow.add_node("fetch_profile", fetch_user_profile_node)
    workflow.add_node("create_strategy", create_personalization_strategy_node)
    workflow.add_node("execute", execute_personalization_node)
    workflow.add_node("error", error_node)

    # Set entry point
    workflow.set_entry_point("fetch_pages")

    # Add conditional edges
    workflow.add_conditional_edges(
        "fetch_pages",
        should_continue,
        {
            "analyze": "analyze",
            "error": "error"
        }
    )

    workflow.add_conditional_edges(
        "analyze",
        should_continue,
        {
            "fetch_profile": "fetch_profile",
            "error": "error"
        }
    )

    workflow.add_conditional_edges(
        "fetch_profile",
        should_continue,
        {
            "create_strategy": "create_strategy",
            "error": "error"
        }
    )

    workflow.add_conditional_edges(
        "create_strategy",
        should_continue,
        {
            "execute": "execute",
            "error": "error"
        }
    )

    workflow.add_conditional_edges(
        "execute",
        should_continue,
        {
            "end": END,
            "error": "error"
        }
    )

    # End points
    workflow.add_edge("error", END)

    return workflow.compile()


# 6. Usage
if __name__ == "__main__":
    # Create the workflow
    app = create_personalization_workflow()

    # Initial state
    initial_state = {
        "user_id": "user123",
        "messages": [],
        "pages_data": {},
        "user_profile": {},
        "selected_page": {},
        "personalization_strategy": "",
        "execution_result": "",
        "current_step": "starting",
        "error_message": ""
    }

    print("🚀 Starting personalization workflow...\n")

    # Run the workflow
    final_result = app.invoke(initial_state)

    print("\n" + "=" * 50)
    print("FINAL RESULT:")
    print("=" * 50)
    print(f"Status: {final_result['current_step']}")
    print(f"User ID: {final_result['user_id']}")
    print(f"Strategy: {final_result.get('personalization_strategy', 'N/A')}")
    print(f"Execution Result: {final_result.get('execution_result', 'N/A')}")

    if final_result.get('error_message'):
        print(f"Error: {final_result['error_message']}")