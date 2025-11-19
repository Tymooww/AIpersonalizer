FROM python:3.10.11-slim

WORKDIR /AIpersonalizer

RUN pip install python-dotenv langchain-openai langchain-community langchain langgraph pymongo pydantic requests ddgs

COPY . .

CMD ["python", "./personalize_page.py"]