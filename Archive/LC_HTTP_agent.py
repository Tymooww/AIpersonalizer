from langchain_core.prompts import PromptTemplate
from langchain_ollama import ChatOllama
from langchain.agents import create_react_agent
import requests
from langchain_core.tools import tool

chosen_llm = ChatOllama(base_url='http://localhost:11434', model="gemma3:4b")
chosen_llm.verbose = True
@tool
def get_weather(latitude: float, longitude: float) -> str:
    """
        Haal de data op uit de request met de juiste latitude en longitude waardes. Als je de tool gebruikt hebt hoef je verder niks te doen.
    """
    response = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=temperature_2m_max,temperature_2m_min")
    data = response.json()
    #print(f"Het weer in {longitude} {latitude} is {data['daily']['time']} met {data['daily']['temperature_2m_max']}°C.")
    return "gelukt!"

# Create prompt template
template = """
Verstuur een request met de tool. Als je dat gedaan hebt ben je klaar en hoef je niks terug te sturen.

Stad: {input}
Tools: {tools}, {tool_names}, {agent_scratchpad}
"""
prompt_template = PromptTemplate(input_variables=['tools', 'agent_scratchpad', 'tool_names', 'input'], template=template)

# Maak agent met de HTTP tool
agent = create_react_agent(llm=chosen_llm, tools=[get_weather], prompt=prompt_template)

# Voer agent aan met vraag
result = agent.invoke({"input": "Amsterdam",
                       "intermediate_steps": [],
                       "agent_scratchpad" : ""})

print(result)