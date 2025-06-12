from vertexai.language_models import TextGenerationModel
from vertexai.generative_models import GenerativeModel, ChatSession
from pytrends.request import TrendReq
from google.cloud import aiplatform
import os
import yfinance as yf
import time


aiplatform.init(project='admazes-vertex-ai-agent-test', location='us-central1')
pytrends = TrendReq(retries=3, hl='en-US', tz=360)

MODEL_NAME = "gemini-2.5-flash-preview-05-20"

def get_ticker_symbol(company_name: str, chat: ChatSession = None) -> str:
    """
    Attempts to get the stock ticker symbol for a given company name.
    Prioritizes a predefined map, then attempts a yfinance search,
    and finally can use the LLM as a last resort or for confirmation.
    """
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
                print(f"Gemini suggested ticker: '{ticker_suggestion}'. Validating...")
                # Validate the LLM's suggestion with yfinance
                try:
                    ticker = yf.Ticker(ticker_suggestion)
                    info = ticker.info
                    if info and 'symbol' in info and info['symbol'] == ticker_suggestion:
                        return ticker_suggestion
                    else:
                        print(f"Gemini's suggestion '{ticker_suggestion}' not validated by yfinance.")
                except Exception:
                    print(f"Gemini's suggestion '{ticker_suggestion}' could not be validated by yfinance.")
            elif ticker_suggestion == "PRIVATE":
                print(f"Gemini identified '{company_name}' as a private company.")
                return None # Indicate private company
        except Exception as e:
            print(f"Error querying Gemini for ticker: {e}")

    # Cannot determine automatically, prompt user
    print(f"Could not automatically determine ticker for '{company_name}'.")
    user_ticker = input(f"Please enter the stock ticker symbol for '{company_name}' (or 'SKIP' if private/not found): ").upper()
    if user_ticker == 'SKIP':
        return None
    return user_ticker

def get_trends_data_multiple(keywords: list):
    """Fetch Google Trends data for multiple keywords at once."""
    time.sleep(5)

    pytrends = TrendReq(hl='en-US', tz=360)

    try:
        pytrends.build_payload(keywords, cat=0, timeframe='today 3-m', geo='US')
        data = pytrends.interest_over_time()
        if not data.empty:
            data = data.drop(labels=['isPartial'], axis=1)
            data = data.fillna(False).infer_objects(copy=False)
            return data.to_dict()
        else:
            return {"message": "No trend data found."}
    except Exception as e:
        return {"error": str(e)}

def get_stock_data(ticker_symbol: str, period: str = '3mo'):
    """Fetch historical stock data using yfinance."""
    if not ticker_symbol:
        return {"message": "No valid ticker symbol provided."}
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period=period)
        if not hist.empty:
            return hist[['Close', 'Volume']].to_dict()
        else:
            return {"message": f"No stock data found for {ticker_symbol}."}
    except Exception as e:
        return {"error": str(e)}

def suggest_competitors(company: str, chat: ChatSession):
    """Use Gemini model to suggest competitors."""
    prompt = f"""
    You are a business market analyst AI. List the top 3 direct competitors of the company '{company}'.
    Provide only the competitor names as a Python list of strings.
    Example: ["Competitor1", "Competitor2", "Competitor3"]
    """
    response = chat.send_message(prompt)
    try:
        competitors = eval(response.text.strip())
        if isinstance(competitors, list):
            return competitors
        else:
            return []
    except:
        return []

def insight(company, all_trends_data, all_stock_data, competitors, chat: ChatSession):
    """Generate detailed comparative marketing and financial insight."""
    prompt = f"""
        You are an expert marketing and financial analyst AI. Below is Google Trends data for the main company '{company}' 
    and its competitors: {competitors}, along with their stock market data. Perform a **competitive analysis** by comparing trends 
    and financial performance between the main company and each competitor. Every conclusion and insight must require data support.

    Identify:
    1. Potential reasons for trend similarities and differences in both search interest and stock performance.
    2. Relative market share (inferred from trends and financial data).
    3. Discuss how observed marketing strategies (inferred from trends) may have correlated with past stock performance trends.
    4. Provide a structured analysis of strengths, weaknesses, opportunities, and threats for each company, based on the provided trends and stock data. Focus on observable data points and market dynamics rather than subjective interpretations.
    5. Make a few financial advises for the company (most important).

    It is suggested to elborate more on the fifth point, less on the first four points
    Ensure all analysis is objective, data-driven, and avoids speculation, financial advice, or any sensitive/controversial topics.

    Google Trends Data:
    {all_trends_data}

    Stock Market Data:
    {all_stock_data}

    Provide a concise, actionable data-driven comparative analysis. Bullet points are encouraged.
    """
    response = chat.send_message(prompt)
    return response.text

def start_chat():
    print("I'm Your Marketing and Financial Assistant. Type 'exit' to quit.")
    model = GenerativeModel(MODEL_NAME)
    chat = model.start_chat()

    while True:
        company_name_input = input("Enter a company name to analyze (e.g., 'Apple', 'Microsoft', or 'exit' to quit): ")
        if company_name_input.lower() == 'exit':
            break

        print(f"Attempting to determine ticker for '{company_name_input}'...")
        company_ticker = get_ticker_symbol(company_name_input, chat)

        if company_ticker is None:
            print(f"Skipping stock analysis for '{company_name_input}' as no valid ticker was found or it's a private company.")
        else:
            print(f"Analyzing: {company_name_input} (Ticker: {company_ticker})")

        print("Asking Gemini model for competitors...")
        competitors = suggest_competitors(company_name_input, chat)
        print(f"Identified competitors: {competitors}")

        all_keywords = [company_name_input] + competitors
        
        competitor_tickers = []
        for comp_name in competitors:
            comp_ticker = get_ticker_symbol(comp_name, chat)
            if comp_ticker:
                competitor_tickers.append(comp_ticker)
            else:
                print(f"Could not determine ticker for competitor '{comp_name}'. Skipping stock data for this competitor.")

        all_tickers = [company_ticker] + competitor_tickers

        print(f"Fetching Google Trends data for: {all_keywords} ...")
        all_trends_data = get_trends_data_multiple(all_keywords)

        print(f"Fetching Stock Market data for: {all_tickers} ...")
        all_stock_data = {}
        for ticker in all_tickers:
            stock_data = get_stock_data(ticker)
            if "error" not in stock_data and "message" not in stock_data:
                all_stock_data[ticker] = stock_data
            else:
                print(f"Could not fetch stock data for {ticker}: {stock_data.get('error', stock_data.get('message', 'Unknown error'))}")
                all_stock_data[ticker] = {"message": "Data not available."} 

        print("Generating **comparative competitive marketing and financial insights** from Gemini model...")
        insights = insight(company_name_input, all_trends_data, all_stock_data, competitors, chat)

        print("\n--- Competitive Marketing and Financial Insights ---")
        print(insights)
        print("---------------------------------------------------\n")

        while True:
            user_question = input("Ask a follow-up (or type 'new' to analyze another company, 'exit' to quit): ")
            if user_question.lower() == 'exit':
                return
            elif user_question.lower() == 'new':
                break
            else:
                response = chat.send_message(user_question)
                print("\n--- Gemini Response ---")
                print(response.text)
                print("-----------------------\n")

if __name__ == "__main__":
    start_chat()