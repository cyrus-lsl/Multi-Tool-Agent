from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from vertexai.generative_models import GenerativeModel, ChatSession
from pytrends.request import TrendReq
import os
from dotenv import load_dotenv
import json
from google.oauth2 import service_account
from google.cloud import bigquery
from google.cloud import aiplatform
import yfinance as yf
import pandas as pd
import time
import requests
import datetime # Import datetime

client = bigquery.Client()

# Query now gets all terms (not just rank 1) for broader general trend analysis,
# but still limited by date for relevance.
QUERY = """
SELECT
   refresh_date AS Day,
   term AS Top_Term,
   rank,
FROM `bigquery-public-data.google_trends.top_terms`
WHERE
   rank = 1
   AND refresh_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 WEEK)
GROUP BY Day, Top_Term, rank
ORDER BY Day DESC
"""

# === Load Google Trends CSV (This will only load it ONCE when FastAPI starts) ===
# For real-time daily updates, you'd need to either:
# 1. Have a BigQuery Scheduled Query update this 'df' daily (as discussed previously).
# 2. Re-query BigQuery directly in 'get_general_trends' or 'get_trends_multiple' if you want live data.
#    For simplicity of this example, let's keep it loaded once, but be aware of its staleness.
try:
    df = client.query(QUERY).to_dataframe()
    # Ensure 'refresh_date' is datetime for filtering later in functions
    df['Day'] = pd.to_datetime(df['Day'])
    df.to_csv("google_trends.csv", index=False)
except Exception as e:
    print(f"Error loading BigQuery data: {e}. 'df' will be empty.")
    df = pd.DataFrame() # Initialize empty dataframe if query fails


# === Vertex AI & PyTrends Setup ===
aiplatform.init(project='admazes-vertex-ai-agent-test', location='us-central1')
pytrends = TrendReq(retries=3, hl='en-US', tz=360)
MODEL_NAME = "gemini-2.5-pro"

load_dotenv()
credentials_info = {
    "type": os.getenv("GCP_TYPE"),
    "project_id": os.getenv("GCP_PROJECT_ID"),
    "private_key_id": os.getenv("GCP_PRIVATE_KEY_ID"),
    "private_key": os.getenv("GCP_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("GCP_CLIENT_EMAIL"),
    "client_id": os.getenv("GCP_CLIENT_ID"),
    "auth_uri": os.getenv("GCP_AUTH_URI"),
    "token_uri": os.getenv("GCP_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("GCP_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("GCP_CLIENT_X509_CERT_URL"),
    "universe_domain": os.getenv("GCP_UNIVERSE_DOMAIN"),
}
gnews_api_key = os.getenv("GNEWS_API_KEY")

# === LLM Setup ===
model = GenerativeModel(MODEL_NAME)
chat = model.start_chat()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Pydantic Models ===
class StartChatRequest(BaseModel):
    company: str

class FollowUpRequest(BaseModel):
    question: str

class QueryRequest(BaseModel):
    query: str

# === Tool Registry ===
AVAILABLE_TOOLS = {
    "get_stock": "Get real-time or historical stock price and volume for a **specific company's ticker**.",
    "get_general_trends": "Get the most recent **general top Google search trends** across various topics. Use this when the user asks for 'new trends', 'trending topics', or 'what's popular'.",
    "get_company_trends": "Get Google Trends data to understand search interest related to a **specific company or keyword**.",
    "get_news": "Get recent news articles from GNews for a **specific keyword or company**.",
    "get_competitors": "Suggest top 3 direct competitors of a **given company**.",
    "get_insight": "Generate a comprehensive market analysis using all tools for a **specific company**.",
    "chat": "General chat or follow-up questions for topics not covered by specific tools."
}

# === LLM Tool Classifier ===
# Modified to distinguish general trends from company trends
def classify_tool_llm(user_input: str, chat: ChatSession) -> str:
    tool_list_str = "\n".join([f"- {tool}: {desc}" for tool, desc in AVAILABLE_TOOLS.items()])
    prompt = f"""
You are an intelligent API router for a market analysis AI.
Your goal is to accurately determine which tool is most appropriate based on the user's request.
Carefully read the user's input and the description of each tool.

If the user asks for general trends, without mentioning a specific company, use `get_general_trends`.
If the user mentions a specific company (e.g., 'Apple trends', 'trends for Tesla'), use `get_company_trends`.

Respond ONLY with the tool name, exactly as written. If no specific tool is perfect, choose 'chat'.

Available tools:
{tool_list_str}

User input:
"{user_input}"

Tool to use:
"""
    try:
        response = chat.send_message(prompt)
        selected_tool = response.text.strip()
        if selected_tool in AVAILABLE_TOOLS:
            return selected_tool
    except Exception as e:
        print(f"LLM classification error: {e}")
        pass # Fallback to chat if LLM fails
    return "chat"

# === Utility Functions ===
def get_ticker_symbol(company_name: str, chat: ChatSession = None) -> str:
    company_name = company_name.lower().strip()
    if chat:
        prompt = f"""
        You are a financial expert. What is the most common stock ticker symbol for the company '{company_name}'?
        If it is a public company, provide only the ticker symbol (like 'TSLA').
        If it is private, respond with 'PRIVATE'.
        If you cannot confidently identify it, respond with 'UNKNOWN'.
        """
        try:
            response = chat.send_message(prompt)
            ticker_suggestion = response.text.strip().upper()

            if ticker_suggestion and ticker_suggestion not in ["PRIVATE", "UNKNOWN"]:
                # Try the raw ticker and some common exchange suffixes
                possible_tickers = [
                    ticker_suggestion,
                    ticker_suggestion + ".L",   # London
                    ticker_suggestion + ".HK",  # Hong Kong
                    ticker_suggestion + ".SI",  # Singapore
                    ticker_suggestion + ".NS",  # NSE India
                    ticker_suggestion + ".AX",  # Australia
                    ticker_suggestion + ".PA", # Paris
                    ticker_suggestion + ".DE", # Germany
                ]

                for ticker in possible_tickers:
                    try:
                        ticker_obj = yf.Ticker(ticker)
                        info = ticker_obj.info # Accessing info triggers a check
                        if info and 'symbol' in info: # Basic check for valid info
                            return ticker
                    except:
                        continue # Try next ticker if this one fails

            elif ticker_suggestion == "PRIVATE":
                return None # Explicitly private
            elif ticker_suggestion == "UNKNOWN":
                return None # LLM couldn't determine
        except Exception as e:
            print(f"Error in get_ticker_symbol LLM call: {e}")
            pass # Fallback to asking user

    # If all fails, fallback to asking user
    return None # Indicate failure to find ticker

def suggest_search_keyword(input_str: str, chat: ChatSession) -> str:
    # This function is now more generic for any search input (company or general)
    prompt = f"""
    You are an expert in online search optimization.
    What is the best single keyword to search Google Trends and News for the input '{input_str}'?
    Return only the keyword.
    """
    response = chat.send_message(prompt)
    return response.text.strip()

# NEW FUNCTION for general trends
def get_general_trends_data(llm_model, num_days: int = 3, num_top_terms: int = 10):
    if df.empty:
        return "⚠️ Trend data is not available. Please ensure BigQuery data loaded correctly."

    # Get data for the most recent 'num_days'
    latest_date = df['Day'].max()
    if pd.isna(latest_date):
        return "⚠️ Trend data is not available (no valid dates found)."

    recent_days = df[df['Day'] >= (latest_date - pd.Timedelta(days=num_days-1))]
    if recent_days.empty:
        return f"📉 No trend data found for the last {num_days} days."

    # Group by day and get top N terms for each day
    trend_summary = {}
    for day in sorted(recent_days['Day'].unique(), reverse=True):
        daily_trends = recent_days[recent_days['Day'] == day].sort_values(by='rank', ascending=True)
        top_terms_for_day = daily_trends['Top_Term'].head(num_top_terms).tolist()
        if top_terms_for_day:
            trend_summary[day.strftime('%Y-%m-%d')] = top_terms_for_day

    if not trend_summary:
        return f"📉 No general top trends found for the last {num_days} days."

    # Format the output for the LLM
    formatted_output = "📈 **Latest Google Trends - Top Terms**:\n\n"
    for day_str, terms in trend_summary.items():
        formatted_output += f"📅 **{day_str}**:\n"
        for i, term in enumerate(terms):
            formatted_output += f"  {i+1}. {term}\n"
        formatted_output += "\n"

    return formatted_output.strip()

# Renamed get_trends_multiple to get_company_trends as per new tool definition
def get_company_trends(company: str, llm_model, limit: int = 5):
    if df.empty:
        return f"⚠️ Trend data for company analysis is not available."

    # Get recent trends
    latest_date = df['Day'].max()
    if pd.isna(latest_date):
        return f"⚠️ Trend data for company analysis is not available (no valid dates found)."
    
    # Filter for the last ~7 days for relevance in company context
    recent_df = df[df['Day'] >= (latest_date - pd.Timedelta(days=6))] 
    if recent_df.empty:
        return f"📉 No recent trend data available to analyze for '{company}'."

    related = []
    
    # Use a simpler, more robust prompt for relevance check
    relevance_prompt_template = f"""
    Evaluate the relationship between the following trend and company.
    Trend: "{{trend_text}}"
    Company: "{company}"

    Does this trend directly relate to the company? Consider news, products, leadership, market position, or public perception.
    Respond with 'YES: [short explanation]' if related, or 'NO' if not.
    """

    for _, row in recent_df.iterrows():
        trend_text = row["Top_Term"]
        # Avoid checking if trend_text is too short or generic unless it's the company name itself
        if len(trend_text) < 3 and trend_text.lower() != company.lower():
            continue

        current_relevance_prompt = relevance_prompt_template.format(trend_text=trend_text)
        try:
            response = llm_model.generate_content(current_relevance_prompt)
            answer = response.text.strip()
            
            if answer.lower().startswith("yes:"):
                explanation = answer[4:].strip()
                related.append((trend_text, explanation))
                if len(related) >= limit:
                    break
        except Exception as e:
            print(f"Error checking trend relevance for '{trend_text}' and '{company}': {e}")
            continue # Skip to next trend if LLM call fails

    if not related:
        return f"📉 No significant Google Trends found directly related to '{company}' in recent data."

    # Format result
    trend_list = "\n".join(f"- **{term}**: {reason}" for term, reason in related)
    return f"📈 LLM-identified trends related to **'{company}'**:\n\n{trend_list}"


def get_news_trends_data_multiple(queries: list):
    all_articles = {}
    for query in queries:
        time.sleep(0.3)
        url = f"https://gnews.io/api/v4/search?q={query}&lang=en&country=us&max=5&token={gnews_api_key}" # Reduced max to 5 for brevity
        try:
            response = requests.get(url)
            if response.status_code == 200:
                articles = response.json().get("articles", [])
                all_articles[query] = articles
            else:
                all_articles[query] = {"error": f"HTTP {response.status_code}", "details": response.text}
        except Exception as e:
            all_articles[query] = {"error": str(e)}
    return all_articles

def get_stock_data(ticker_symbol: str, period: str = '7d'):
    if not ticker_symbol:
        return "No valid ticker symbol provided."
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period=period)
        if hist.empty:
            return f"No stock data found for {ticker_symbol}."

        # Format stock price info
        price_text = f"**Stock data for {ticker_symbol} over the last {period}:**\n"
        for date, row in hist.iterrows():
            date_str = date.strftime('%Y-%m-%d')
            # Check for NaN values before formatting
            if pd.isna(row['Close']):
                close_price = "N/A"
            else:
                close_price = f"${row['Close']:.2f}"
            
            if pd.isna(row['Volume']):
                volume = "N/A"
            else:
                volume = f"(Vol: {int(row['Volume']/1e6)}M)" if row['Volume'] > 0 else "(Vol: 0)"

            price_text += f"- {date_str}: {close_price} {volume}\n"

        # Ask LLM to generate natural summary
        prompt = f"""
Given the following 7-day stock data for {ticker_symbol}, write a brief, human-style chatbot response summarizing its recent performance.
Focus on key movements (e.g., up, down, stable, large volume days).
Use natural language. Avoid technical jargon where possible.

Data:
{price_text}
"""
        response = chat.send_message(prompt)
        return response.text.strip()

    except Exception as e:
        return f"Error fetching stock data for {ticker_symbol}: {str(e)}. It might be a private company, incorrect ticker, or no data available."

def suggest_competitors(company: str, chat: ChatSession):
    prompt = f"""
    You are a business analyst AI. List the top 3 direct competitors of the company '{company}'.
    Provide only a Python list: ["Competitor1", "Competitor2", "Competitor3"]
    If no clear competitors are known, return an empty list: []
    """
    response = chat.send_message(prompt)
    try:
        competitors = eval(response.text.strip())
        return competitors if isinstance(competitors, list) else []
    except:
        print(f"Error parsing competitor list from LLM: {response.text}")
        return []

def insight(company, all_trends_data, news_data, all_stock_data, competitors, chat: ChatSession):
    data_note = []
    if isinstance(all_trends_data, str) and ("error" in all_trends_data or "not available" in all_trends_data):
        data_note.append("Google Trends Data issue detected.")
    if not news_data or (isinstance(news_data, dict) and any("error" in v for v in news_data.values())):
        data_note.append("News data missing or incomplete.")
    if not all_stock_data or any("Error" in v for v in all_stock_data.values()):
        data_note.append("Stock data missing or incomplete for some tickers.")
    
    data_warning_str = "\nWarning:\n" + "\n".join([f"* {note}" for note in data_note]) if data_note else ""

    prompt = f"""
    {data_warning_str}

    Provide a comprehensive market analysis and actionable financial suggestions for '{company}', considering its competitors {competitors}.

    Use the following data:
    Trends Data: {all_trends_data}
    News Data: {news_data}
    Stock Data: {all_stock_data}

    Include the following sections:
    1.  **Market & Trend Summary**: Summarize overall market conditions and relevant trends affecting the company and its industry.
    2.  **Market Share & Competitive Insights**: Analyze the company's position relative to its competitors.
    3.  **Notable Events**: Highlight key recent news or events impacting the company.
    4.  **SWOT Summary**: Briefly outline Strengths, Weaknesses, Opportunities, and Threats.
    5.  **Actionable Financial Suggestions**: Provide concrete, practical financial advice or recommendations based on the analysis.

    Ensure the response is well-structured, easy to read, and professional.
    """
    try:
        response = chat.send_message(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Error generating insight: {str(e)}"

# === API Endpoints ===
@app.post("/start_chat")
def start_chat_api(req: StartChatRequest):
    company = req.company
    company_ticker = get_ticker_symbol(company, chat)
    competitors = suggest_competitors(company, chat)
    
    # Prepare keywords and tickers for all data sources
    company_keyword = suggest_search_keyword(company, chat)
    competitor_keywords = [suggest_search_keyword(c, chat) for c in competitors]
    all_keywords = [company_keyword] + competitor_keywords
    
    # Filter out None from tickers
    valid_competitor_tickers = [get_ticker_symbol(c, chat) for c in competitors]
    all_tickers = [ticker for ticker in [company_ticker] + valid_competitor_tickers if ticker]

    trends_data = {kw: get_company_trends(kw, model) for kw in all_keywords} # Use get_company_trends
    news_data = get_news_trends_data_multiple(all_keywords)
    stock_data = {ticker: get_stock_data(ticker) for ticker in all_tickers if ticker}

    insights = insight(company, trends_data, news_data, stock_data, competitors, chat)
    return {"insight": insights}

@app.post("/follow_up")
def follow_up_api(req: FollowUpRequest):
    query = req.question.strip()

    prompt = f"""
You're a helpful assistant in a market analysis AI chatbot.

The user asked a follow-up question: "{query}"

Reply naturally in a friendly tone. If the question is vague, ask what exactly they want (e.g., stock, news, or trends).
Don't return JSON, just a natural chatbot response.
Avoid repeating the user question unless it's helpful.
"""

    try:
        response = chat.send_message(prompt)
        return {"reply": response.text.strip()}
    except Exception as e:
        return {"reply": f"⚠️ Follow-up error: {str(e)}"}


@app.post("/query")
def query_api(req: QueryRequest):
    user_query = req.query.strip()

    # Step 1: Ask the LLM to decide what tool to use
    tool = classify_tool_llm(user_query, chat) # Use the enhanced classifier

    # Step 2: Run the selected tool
    if tool == "get_stock":
        company_or_ticker = user_query # Assume user might input company or ticker
        ticker = get_ticker_symbol(company_or_ticker, chat)
        if ticker:
            return {"reply": get_stock_data(ticker)}
        return {"reply": "❌ Couldn't determine a valid public stock ticker for that. Please provide an exact ticker or public company name."}

    elif tool == "get_general_trends":
        return {"reply": get_general_trends_data(model)} # No keyword needed for general trends

    elif tool == "get_company_trends": # New tool handler
        # Here, the LLM needs to extract the company name from the user_query
        company_name_prompt = f"""
        Extract the primary company name from the following user query. If no specific company is mentioned, just return "general".
        User query: "{user_query}"
        Company name:
        """
        response = chat.send_message(company_name_prompt)
        company_for_trends = response.text.strip()
        
        if company_for_trends.lower() == "general" or not company_for_trends:
            return {"reply": get_general_trends_data(model)} # Fallback to general if company extraction fails
        
        return {"reply": get_company_trends(company_for_trends, model)}

    elif tool == "get_news":
        keyword_for_news = suggest_search_keyword(user_query, chat)
        raw_news = get_news_trends_data_multiple([keyword_for_news])
        formatted_news = ""

        for key, val in raw_news.items():
            if isinstance(val, list):
                articles = "\n".join(
                    [f"- [{a['title']}]({a['url']})" for a in val[:5]]
                )
                formatted_news += f"📰 **News for '{key}'**:\n{articles}\n\n"
            elif isinstance(val, dict) and "error" in val:
                formatted_news += f"⚠️ **News for '{key}'** – Error: {val['error']} – {val.get('details', '')}\n\n"
            else:
                formatted_news += f"⚠️ **News for '{key}'** – Unexpected news format.\n\n"

        return {"reply": formatted_news.strip() or "⚠️ No news available for that query."}

    elif tool == "get_competitors":
        # Here, the LLM needs to extract the company name from the user_query
        company_name_prompt = f"""
        Extract the primary company name from the following user query.
        User query: "{user_query}"
        Company name:
        """
        response = chat.send_message(company_name_prompt)
        company_for_competitors = response.text.strip()
        
        if not company_for_competitors:
             return {"reply": "Please specify the company for which you want to find competitors."}

        competitors = suggest_competitors(company_for_competitors, chat)
        return {
            "reply": f"🏢 **Top Competitors of `{company_for_competitors}`**:\n- " + "\n- ".join(competitors)
            if competitors
            else f"⚠️ No competitors found for `{company_for_competitors}`."
        }

    elif tool == "get_insight":
        # Here, the LLM needs to extract the company name from the user_query
        company_name_prompt = f"""
        Extract the primary company name from the following user query.
        User query: "{user_query}"
        Company name:
        """
        response = chat.send_message(company_name_prompt)
        company_for_insight = response.text.strip()
        
        if not company_for_insight:
            return {"reply": "Please specify the company for which you want a market insight."}

        return start_chat_api(StartChatRequest(company=company_for_insight))

    elif tool == "chat":
        return follow_up_api(FollowUpRequest(question=user_query))

    # Fallback for unexpected tool classification
    return {"reply": f"I'm sorry, I'm not sure how to handle '{user_query}'. Could you please rephrase or specify if you're looking for stock, news, or trends?"}