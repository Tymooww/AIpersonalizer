from typing import Dict, TypedDict
from langgraph.graph import StateGraph

class AgentState(TypedDict): # State schema
    message : str
    name : str

def greeting_node(state: AgentState) -> AgentState:
    """Simple node that adds a greeting message to the state."""

    state['message'] = "Hey " + state['name'] + ", how is your day going?"
    return state

graph = StateGraph(AgentState)
graph.add_node("greeter", greeting_node)
graph.set_entry_point("greeter")
graph.set_finish_point("greeter")

app = graph.compile()

result = app.invoke({"name": "bob"})
print(result["message"])