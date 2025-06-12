from vertexai.language_models import TextGenerationModel
from vertexai.generative_models import GenerativeModel, ChatSession
from pytrends.request import TrendReq
from google.cloud import aiplatform
import os
import yfinance as yf
import time
import requests
import praw
from bs4 import BeautifulSoup

# Initialize APIs
aiplatform.init(project='admazes-vertex-ai-agent-test', location='us-central1')
pytrends = TrendReq(retries=3, hl='en-US', tz=360)
MODEL_NAME = "gemini-2.5-flash-preview-05-20"

# GNews API key
gnews_api_key = "998e6200236374c04b469a2d8190fd47"


def get_ticker_symbol(company_name: str, chat: ChatSession = None) -> str:
    company_name_lower = company_name.lower().strip()
    if chat:
        llm_prompt = f"""
        You are a financial expert. For the company name '{company_name}', what is its most common stock ticker symbol?
        If it is a public company, provide only the ticker symbol.
        If it is a private company or has no widely recognized stock ticker, respond with 'PRIVATE'.
        Example Public: AAPL
        Example Private: PRIVATE
        """
        try:
            response = chat.send_message(llm_prompt)
            ticker_suggestion = response.text.strip().upper()
            if ticker_suggestion and ticker_suggestion != "PRIVATE":
                try:
                    ticker = yf.Ticker(ticker_suggestion)
                    info = ticker.info
                    if info and 'symbol' in info and info['symbol'] == ticker_suggestion:
                        return ticker_suggestion
                except:
                    pass
            elif ticker_suggestion == "PRIVATE":
                return None
        except:
            pass

    user_ticker = input(f"Please enter the stock ticker symbol for '{company_name}' (or 'SKIP'): ").upper()
    return None if user_ticker == 'SKIP' else user_ticker


def get_trends_data_multiple(keywords: list):
    time.sleep(5)
    results = {}
    
    for keyword in keywords:
        try:
            time.sleep(2)  # To respect the 4-requests/sec GNews limit as well
            pytrends.build_payload([keyword], cat=0, timeframe='today 12-m', geo='', gprop='')
            data = pytrends.interest_over_time()
            if not data.empty:
                data = data.drop(columns=['isPartial'], errors='ignore')
                results[keyword] = data[keyword].to_dict()
            else:
                results[keyword] = {"message": "No trend data found."}
        except Exception as e:
            results[keyword] = {"error": str(e)}

    return results
    

def get_news_trends_multiple(queries: list):
    all_articles = {}
    for query in queries:
        time.sleep(0.3)  # Respect rate limit (max 4 req/sec)
        url = f"https://gnews.io/api/v4/search?q={query}&lang=en&country=us&max=25&token={gnews_api_key}"
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


def get_stock_data(ticker_symbol: str, period: str = '3mo'):
    if not ticker_symbol:
        return {"message": "No valid ticker symbol provided."}
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period=period)
        if not hist.empty:
            return hist[['Close', 'Volume']].to_dict()
        return {"message": f"No stock data found for {ticker_symbol}."}
    except Exception as e:
        return {"error": str(e)}


def suggest_competitors(company: str, chat: ChatSession):
    prompt = f"""
    You are a business market analyst AI. List the top 3 direct competitors of the company '{company}'.
    Provide only the competitor names as a Python list of strings.
    Example: ["Competitor1", "Competitor2", "Competitor3"]
    """
    response = chat.send_message(prompt)
    try:
        competitors = eval(response.text.strip())
        return competitors if isinstance(competitors, list) else []
    except:
        return []


def insight(company, all_trends_data, news_data, all_stock_data, competitors, chat: ChatSession):
    # Check for missing data sources
    data_note = ""
    if isinstance(all_trends_data, dict) and ("error" in all_trends_data or "message" in all_trends_data):
        data_note += "*   **Google Trends Data:** The provided Google Trends data returned an error, preventing analysis of search interest and popularity trends for Amazon and its competitors.\n"
    if not news_data or isinstance(news_data, dict):
        data_note += "*   **News Mentions:** No news mentions were provided, thus a qualitative analysis of recent company-specific events or public sentiment is not possible based on this dataset.\n"
    if data_note:
        data_note = "Please note that the following data sources are unavailable or contain errors, which limits the scope of this analysis:\n\n" + data_note + "\nThe competitive analysis, inferred market share, notable events, and SWOT will primarily draw insights from the **Stock Market Data** only.\n\n"

    prompt = f"""
    {data_note}
    You are an expert marketing and financial analyst AI. Below is data for the company '{company}' and its competitors: {competitors}.

    Google Trends Data:
    {all_trends_data}

    News Mentions:
    {news_data}

    Stock Market Data:
    {all_stock_data}

    Please provide:
    1. Competitive analysis on trends, news, and stock.
    2. Inferred market share and visibility.
    3. Notable events or campaigns affecting performance.
    4. SWOT analysis (short version).
    5. Strategic financial suggestions for '{company}' only (focus more on here).

    Make the insights 
    1. bullet-pointed, easy to read
    2. Every suggestions MUST be data-supported, and avoid speculation.
    """
    response = chat.send_message(prompt)
    return response.text


def start_chat():
    print("Multi-Source Marketing & Finance Agent. Type 'exit' to quit.")
    model = GenerativeModel(MODEL_NAME)
    chat = model.start_chat()

    while True:
        company_name_input = input("Enter a company name: ")
        if company_name_input.lower() == 'exit':
            break

        company_ticker = get_ticker_symbol(company_name_input, chat)
        competitors = suggest_competitors(company_name_input, chat)
        all_keywords = [company_name_input] + competitors

        competitor_tickers = [get_ticker_symbol(c, chat) for c in competitors]
        all_tickers = [company_ticker] + competitor_tickers

        trends_data = get_trends_data_multiple(all_keywords)
        news_data = get_news_trends_multiple([company_name_input] + competitors)
        stock_data = {ticker: get_stock_data(ticker) for ticker in all_tickers if ticker}

        print("Generating insights...")
        insights = insight(company_name_input, trends_data, news_data, stock_data, competitors, chat)
        print("\n--- Insights ---\n")
        print(insights)
        print("\n----------------\n")

        while True:
            user_question = input("Follow-up (or 'new', 'exit'): ")
            if user_question.lower() == 'exit':
                return
            elif user_question.lower() == 'new':
                break
            else:
                response = chat.send_message(user_question)
                print("\n--- Gemini Response ---\n")
                print(response.text)
                print("\n------------------------\n")


if __name__ == "__main__":
    start_chat()
