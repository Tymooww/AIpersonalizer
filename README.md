# AI personalizer
This application personalizes pages from ContentStack based on the industry of a user.

This is how it works:
1. The website will send a request asking for personalization.
2. AI personalizer will go through the personalization process and save the pages in MongoDB.
3. AI personalizer sends a failed or success response.
4. The website will then request the page the user is currently on in a request after receiving a success response.
5. AI personalizer will request the page from MongoDB.
6. AI personalizer sends the page as response to the website.

## Setting up AI personalizer
Before running the project, two .env files need to be added with some credentials. One for the MongoDB docker container and the other one for AI personalizer itself.

### MongoDB docker container environment variables
Create a .env in the MongoDB storage folder, with the following credentials:

- MONGO_INITDB_ROOT_USERNAME: The database admin username
- MONGO_INITDB_ROOT_PASSWORD: The database admin password

```
MONGO_INITDB_ROOT_USERNAME=<Your db admin username>
MONGO_INITDB_ROOT_PASSWORD=<Your db admin password>
```

### AI personalizer environment variables
Create a .env in de AIpersonalizer folder, with the following credentials:

1. ContentStack configuration:
You can find these variables in the settings of the stack you are working in.
- CMS_API_KEY: The API key of your Stack
- CMS_DELIVERY_TOKEN= The delivery token of you Stack
- CMS_MANAGEMENT_TOKEN= The management token of you Stack
- CMS_ENVIRONMENT= The environment of your Stack where you want to get the pages from
- CMS_BASE_URL= The URL according to the region (EU or US)

2. Lytics configuration
You can find these variables in the settings of the Lytics dashboard (In ContentStack press the nine dot button in the right upper corner and click on data and insights).
- CDP_API_KEY= The Lytics API key
- CDP_BASE_URL= The Lytics base URL

3. Bonzai configuration
You can find these variables in Bonzai, read the Bonzai documentation to know how (https://confluence.hosted-tools.com/display/IOGPT/Bonzai) 
- BONZAI_API_KEY= A Bonzai API key that is tied to a Bridge project
- BONZAI_URL= The base URL of Bonzai
- BONZAI_MODEL= The chosen model of Bonzai

4. Mongo database configuration
You create these variables yourself in the MongoDB docker-compose environment variables.
- MONGODB_DEV_URL= The MongoDB localhost URL (used when hosting locally in docker)
- MONGODB_URL= The MongoDB deployment URL (used when hosted in the cloud)
- MONGODB_DATABASE= The database name
- ENVIRONMENT= The environment where MongoDB is deployed (development = locally, anything else = cloud)

5. Authentication details
Basic Auth is used as API protection. These variables can be created by yourself.
- AUTH_USERNAME= The Basic Auth username
- AUTH_PASSWORD= The Basic Auth password

```
# ContentStack configuration
CMS_API_KEY=<Your Stack API key>
CMS_DELIVERY_TOKEN=<Your Stack delivery token>
CMS_MANAGEMENT_TOKEN=<Your Stack management token>
CMS_ENVIRONMENT=<Your Stack environment>
CMS_BASE_URL=https://eu-api.contentstack.com/v3

# Lytics configuration
CDP_API_KEY=<Your Lytics API key>
CDP_BASE_URL=https://api.lytics.io/api

# Bonzai configuration
BONZAI_API_KEY=<Your Bonzai API key>
BONZAI_URL=https://api-v2.bonzai.iodigital.com
BONZAI_MODEL=gpt-4o-mini

# Mongo database configuration
MONGODB_DEV_URL=mongodb://localhost:27017/
MONGODB_URL=<Your cloud hosted MongoDB URL>
MONGODB_DATABASE=personalizedpages
ENVIRONMENT=development

# Authentication details
AUTH_USERNAME=<Your Basic Auth username>
AUTH_PASSWORD=<Your Basic Auth password>
```

## Running AI personalizer
You can open AI personalizer in any Python compatible IDE (such as PyCharm).

1. To run AI personalizer install Python 3.10.11 and set it up as interpreter.
2. Then install the required dependencies:
```
pip install -r requirements.txt
```
3. Execute the docker-compose.yml of the MongoDB storage to start MongoDB.
4. Run app.py and the Flask API server will start. 

Important note: if you want to run AI personalizer in a docker container as well, make sure to set the MongoDB URL to the docker bridge IP.

Lastly: Make sure to set up the website renderer as well to see the pages loaded in the website (see the Personalized Website Renderer project for more information).