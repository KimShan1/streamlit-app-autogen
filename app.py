import streamlit as st
import openai
from apify_client import ApifyClient
from typing_extensions import Annotated
from datetime import datetime
import json
import autogen
from autogen.agentchat.contrib.web_surfer import WebSurferAgent
from autogen import register_function
import sys


# Add path to autogen if it's a local module
sys.path.append('/path/to/autogen')

# Initialize session state for API keys
if 'azure_api_key' not in st.session_state:
    st.session_state.azure_api_key = ""
if 'apify_api_key' not in st.session_state:
    st.session_state.apify_api_key = ""
if 'bing_api_key' not in st.session_state:
    st.session_state.bing_api_key = ""
if 'response' not in st.session_state:
    st.session_state.response = ""

# Streamlit UI
st.title("Autogen Chatbot Interface to Search Reddit Posts and Scrape them")

# Input fields for API keys
st.sidebar.header("API Key Configuration")
azure_api_key = st.sidebar.text_input("Azure OpenAI API Key", type="password")
apify_api_key = st.sidebar.text_input("Apify API Key", type="password")
bing_api_key = st.sidebar.text_input("Bing API Key", type="password")

if st.sidebar.button("Save Keys"):
    st.session_state.azure_api_key = azure_api_key
    st.session_state.apify_api_key = apify_api_key
    st.session_state.bing_api_key = bing_api_key
    st.sidebar.success("API keys saved!")


config_list = [
    {
        'model' : 'gpt-4-model-ai', 
        'api_key': st.session_state.azure_api_key,
        'base_url': 'https://oaibpa75y72jvmsfw36.openai.azure.com/',
        'api_type': 'azure',
        'api_version': '2024-02-15-preview',
    }
]

llm_config = {
    "timeout": 600,   # kills the request after a certain amount of time
    "cache_seed": 42, 
    "config_list": config_list,
    "temperature": 0, # the less creative the responses
}

summarizer_llm_config = {
    "timeout": 600,   # kills the request after a certain amount of time
    "cache_seed": None, 
    "config_list": config_list,
    "temperature": 0, # the less creative the responses
}

# # Function to generate chatbot responses
# def generate_response(prompt):
#     chat_result = user_proxy.initiate_chat(
#         manager,
#         message=prompt,
#         summary_method="reflection_with_llm",
#         summary_args={
#             "summary_prompt": """Summarize for each and every scraped reddit content and format the summary as EXACTLY as follows:
# {
#     URL: url,
#     Date Published: date of post or comment,
#     Date Scraped: date of content scraped,
#     Title: title of post,
#     Summary: summary of scraped url with main findings and conclusions,
#     Key Features, their sentiment and detail reason explaining the sentiment: key features and insights,
#     Brands, their sentiment and detail reason explaining the sentiment: key features and insights for brands discussed,
# }
# Ensure that all summaries follow this structure exactly.
# If any data is missing or cannot be found, use "N/A" for the missing data.
# Provide the summary in this exact format for each of the scraped contents.
# """
#         },
#     )
#     return chat_result.summary

# Function to generate chatbot responses
def generate_response(prompt,summary_prompt):
    chat_result = user_proxy.initiate_chat(
        manager,
        message=prompt,
        summary_method="reflection_with_llm",
        summary_args={
            "summary_prompt": summary_prompt
        },
    )
    return chat_result.summary


def scrape_reddit(url: Annotated[str, "The URL of the reddit page to scrape"]) -> Annotated[str, "Scraped content"]:
    # Initialize the ApifyClient with your API token
    client = ApifyClient(token=st.session_state.apify_api_key)

    # Prepare the Actor input
    run_input = {
        "startUrls": [{"url": url}], 
        "skipComments": False,
        "searchPosts": False, # Will search for posts with the provided search
        "searchComments": True,
        "searchCommunities": False,
        "searchUsers": False,
        "sort": "comments", # Sort search by Relevance, Hot, Top, New or Comments
        "time": "all",# Filter posts by last hour, week, day, month or year
        "includeNSFW": False, # You can choose to include or exclude NSFW content from your search
        "maxComments": 5, # The maximum number of comments that will be scraped for each Comments Page
        "scrollTimeout": 40,# Set the timeout in seconds in which the page will stop scrolling down to load new items
        "proxy":  {"useApifyProxy":True},
        "debugMode": False,
    }

    # Run the Actor and wait for it to finish
    run = client.actor("trudax/reddit-scraper-lite").call(run_input=run_input)

    # Fetch and print Actor results from the run's dataset (if there are any)
    scraped_data = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            body = item.get("body", "")
            created_at = item.get("createdAt", "")
            data_type = item.get("dataType", "")
            scraped_data.append({
            "url": url,    
            "created_at": created_at,
            "data_type": data_type,
            "body": body
        })
    
    # Convert scraped data to text for return
    text_data = "\n".join(f"{entry['created_at']} | {entry['data_type']}: {entry['body']}" for entry in scraped_data)

    # Save the scraped data to a JSON file
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"scraped_data_{timestamp}.json"
    with open(filename, "w") as file:
        json.dump(scraped_data, file, indent=4)

        
    average_token = 0.75
    max_tokens = 20000  # slightly less than max to be safe 32k
    text_data = text_data[: int(average_token * max_tokens)]
    
    return text_data

# Agent definitions

web_surfer = WebSurferAgent(
    name = "web_surfer",
    llm_config = llm_config,
    summarizer_llm_config = summarizer_llm_config,
    browser_config = {"viewport_size": 4096, "bing_api_key":st.session_state.bing_api_key}
)

scraper_agent_reddit = autogen.ConversableAgent(
    "reddit_scraper",
    llm_config={"config_list": config_list},
    system_message="reddit_scraper. You are a reddit scrapper and your task is to scrape all web pages provided by the `web_surfer` and save the information using the tools provided."
    "Your goal is to scrape all the results returned by the `web_surfer`."
    "Continue scraping until all web results have been processed."
    "Returns 'TERMINATE' when the scraping is done.",
    description="A reddit scraper tasked with scraping all URLs returned by the `web_surfer` and saving the information using the provided tools."
    "Scrape all urls returned by the `web_surfer`."
    "I am ONLY allowed to speak **immediately** after `web_surfer`.",
)

engineer = autogen.AssistantAgent(
    name="Engineer",
    llm_config=llm_config,
    system_message="""Engineer.
Your role is strictly to write Python code as requested by other agents involved in web interaction tasks, such as the `web_surfer` and the `reddit_scraper`. 
Ensure code is executable, complete, and standalone. Do not make assumptions out of nowhere, and do not provide hypothetical code nor only examples.
Ensure the code directly solves the tasks required.
The user cannot modify your code, so avoid suggesting modifications or partial code snippets which requires others to modify. Directly address any errors by revising the code until it is executed by the Executor as expected without errors.
"""
)

executor = autogen.UserProxyAgent(
    name="Executor",
    human_input_mode="NEVER",
    code_execution_config={
        "last_n_messages": 3, # Experimental: The number of messages to look back for code execution. If set to 'auto', it will scan backwards through all messages arriving since the agent last spoke, which is typically the last time execution was attempted
        "work_dir": "files",
        "use_docker": False,
    }, 
    system_message="""Executor.
Execute scripts and code provided by the `Engineer` or `reddit_scraper` and report the results.
Returns 'TERMINATE' when executing is done.
"""
)

user_proxy = autogen.ConversableAgent(
    name ="user_proxy",
    llm_config=False,
    human_input_mode="NEVER", #he agent will never prompt for human input. Under this mode, the conversation stops when the number of auto reply reaches the max_consecutive_auto_reply or when is_termination_msg is True.
    code_execution_config=False,
    default_auto_reply="Please continue if not finished, otherwise return 'TERMINATE'.",
    is_termination_msg=lambda x: True,
    # system_message="Pass the result from web_surfer to scraper_agent_reddit"
)

group_chat = autogen.GroupChat(
    agents=[user_proxy, web_surfer, scraper_agent_reddit, engineer, executor], 
    messages=[], 
    max_round=10,
    send_introductions=True,
    speaker_selection_method="auto")


manager = autogen.GroupChatManager(
    groupchat=group_chat, 
    llm_config = llm_config
)

# Register the function with the agents.
register_function(
    scrape_reddit,
    caller=scraper_agent_reddit,
    executor=executor,
    name="scrape_reddit",
    description="Scrape a reddit post and return the content.",
)


# Suggestion text
st.markdown("**Suggestion:** Write your input similar to the following structure:")
st.markdown("> Search the web for information about *Topic* on Reddit.")

user_input = st.text_input("You: ", "Hello, please let me know what you want to search?")

summary_prompt = st.text_area("Summary Prompt: ", """Summarize for each and every scraped reddit content and format the summary as EXACTLY as follows:
{
    URL: url,
    Date Published: date of post or comment,
    Title: title of post,
    Summary: summary of scraped url with main findings and conclusions,
    Key Features, their sentiment and detail reason explaining the sentiment: key features and insights,
}
Ensure that all summaries follow this structure exactly.
If any data is missing or cannot be found, use "N/A" for the missing data.
Provide the summary in this exact format for each of the urls.
""")

if st.button("Send"):
        # Generate the response and initialize the agents
        response = generate_response(user_input, summary_prompt)
        st.session_state.response = response  # Update the session state with the generated response

        if 'messages' not in st.session_state:
            st.session_state.messages = []

        user_message = {"role": "user", "content": user_input}
        bot_message = {"role": "assistant", "content": response}

        st.session_state.messages.append(user_message)
        st.session_state.messages.append(bot_message)

        st.text_area("Bot:", response, height=200)

        # Display conversation history
        for message in st.session_state.messages:
            if message['role'] == 'user':
                st.text(f"You: {message['content']}")
            else:
                st.text(f"Bot: {message['content']}")
         
         # Add a button to save the results
        if st.session_state.response:
            st.download_button(
                label="Download Results",
                data=json.dumps(st.session_state.response, indent=4),
                file_name=f"structured_summary_{datetime.now().strftime('%Y%m%d%H%M%S')}.json",
                mime="application/json"
            )
else:
    st.error("Please enter and save your API")

# Activate virtual environment: source venvstreamlit/bin/activate
# Run App streamlit run app.py