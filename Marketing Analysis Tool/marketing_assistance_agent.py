from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from vertexai.language_models import TextGenerationModel
from vertexai.generative_models import GenerativeModel, ChatSession
from pytrends.request import TrendReq
from google.cloud import aiplatform
import yfinance as yf
import time
import requests

# Initialize APIs
aiplatform.init(project='admazes-vertex-ai-agent-test', location='us-central1')
pytrends = TrendReq(retries=3, hl='en-US', tz=360)
MODEL_NAME = "gemini-2.5-flash-preview-05-20"

# GNews API key
gnews_api_key = "998e6200236374c04b469a2d8190fd47"

# Gemini model and chat session
model = GenerativeModel(MODEL_NAME)
chat = model.start_chat()

app = FastAPI()

# Allow CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this to your frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic request models
class StartChatRequest(BaseModel):
    company: str

class FollowUpRequest(BaseModel):
    question: str

# --- Your Original Functions ---

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
    return None

def get_trends_data_multiple(keywords: list):
    time.sleep(5)
    results = {}
    for keyword in keywords:
        try:
            time.sleep(2)
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
        time.sleep(0.3)
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
    data_note = ""
    if isinstance(all_trends_data, dict) and ("error" in all_trends_data or "message" in all_trends_data):
        data_note += "* Google Trends Data issue detected.\n"
    if not news_data or isinstance(news_data, dict):
        data_note += "* News data missing or incomplete.\n"
    if data_note:
        data_note = "Warning:\n" + data_note

    prompt = f"""
    {data_note}
    Provide insights for '{company}' and competitors {competitors}.
    
    Trends Data: {all_trends_data}
    News Data: {news_data}
    Stock Data: {all_stock_data}
    Generate:
    1. Competitive analysis.
    2. Market share insights.
    3. Notable events.
    4. SWOT summary.
    5. Actionable financial suggestions.
    """
    response = chat.send_message(prompt)
    return response.text

# --- FastAPI Routes ---

@app.post("/start_chat")
def start_chat_api(req: StartChatRequest):
    company = req.company
    company_ticker = get_ticker_symbol(company, chat)
    competitors = suggest_competitors(company, chat)
    all_keywords = [company] + competitors

    competitor_tickers = [get_ticker_symbol(c, chat) for c in competitors]
    all_tickers = [company_ticker] + competitor_tickers

    trends_data = get_trends_data_multiple(all_keywords)
    news_data = get_news_trends_multiple([company] + competitors)
    stock_data = {ticker: get_stock_data(ticker) for ticker in all_tickers if ticker}

    insights = insight(company, trends_data, news_data, stock_data, competitors, chat)
    return {"insight": insights}

@app.post("/follow_up")
def follow_up_api(req: FollowUpRequest):
    response = chat.send_message(req.question)
    return {"reply": response.text}
