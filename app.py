"""
Streamlit app for Google Search Console data analysis with Claude AI chat
"""

import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
import os
from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Scopes required for Search Console API
SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']
API_SERVICE_NAME = 'searchconsole'
API_VERSION = 'v1'

# Load API key from environment
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

# Initialize session state
if 'claude_api_key' not in st.session_state:
    st.session_state.claude_api_key = ANTHROPIC_API_KEY
if 'gsc_data' not in st.session_state:
    st.session_state.gsc_data = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'domain' not in st.session_state:
    st.session_state.domain = ''
if 'last_response_cut_off' not in st.session_state:
    st.session_state.last_response_cut_off = False
if 'last_response_text' not in st.session_state:
    st.session_state.last_response_text = ''

def authenticate():
    """Authenticate with Google Search Console API."""
    creds = None
    
    # Check for saved credentials
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # If no valid credentials, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                st.error("ERROR: credentials.json not found! Please place your OAuth credentials file as 'credentials.json' in this directory.")
                return None
            
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save for next time
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    return creds

def fetch_gsc_data(service, site_url, start_date, end_date, dimensions):
    """Fetch data from Google Search Console."""
    try:
        request = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': dimensions,
            'rowLimit': 25000
        }
        
        response = service.searchanalytics().query(
            siteUrl=site_url,
            body=request
        ).execute()
        
        return response.get('rows', [])
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return []

def format_data(rows, dimensions):
    """Format API response into readable data."""
    formatted = []
    for row in rows:
        item = {}
        if 'keys' in row:
            for i, dim in enumerate(dimensions):
                item[dim] = row['keys'][i] if i < len(row['keys']) else ''
        item['clicks'] = row.get('clicks', 0)
        item['impressions'] = row.get('impressions', 0)
        item['ctr'] = round(row.get('ctr', 0), 4)
        item['position'] = round(row.get('position', 0), 2)
        formatted.append(item)
    return formatted

def calculate_summary_stats(queries, pages):
    """Calculate summary statistics from GSC data."""
    if not queries and not pages:
        return None
    
    all_data = queries + pages
    
    total_clicks = sum(item['clicks'] for item in all_data)
    total_impressions = sum(item['impressions'] for item in all_data)
    
    if total_impressions > 0:
        avg_ctr = total_clicks / total_impressions
    else:
        avg_ctr = 0
    
    if all_data:
        avg_position = sum(item['position'] for item in all_data) / len(all_data)
    else:
        avg_position = 0
    
    return {
        'total_clicks': total_clicks,
        'total_impressions': total_impressions,
        'avg_ctr': avg_ctr,
        'avg_position': avg_position,
        'query_count': len(queries),
        'page_count': len(pages)
    }

def call_claude_api(api_key, messages, gsc_data):
    """Call Claude API with chat history and GSC data context."""
    try:
        if not api_key:
            return "Error: Claude API key is not set. Please set ANTHROPIC_API_KEY in your .env file.", False
        client = Anthropic(api_key=api_key)
        
        # Sort data by clicks for most relevant examples
        queries_sorted = sorted(gsc_data.get('queries', []), key=lambda x: x.get('clicks', 0), reverse=True)
        pages_sorted = sorted(gsc_data.get('pages', []), key=lambda x: x.get('clicks', 0), reverse=True)
        
        # Get top performers for context (balance between completeness and token limits)
        top_queries = queries_sorted[:300]
        top_pages = pages_sorted[:300]
        
        summary = gsc_data.get('summary', {})
        
        # Prepare system message with GSC data context
        system_message = f"""You are an SEO analyst helping analyze Google Search Console data.

Domain: {gsc_data.get('domain', 'unknown')}
Date Range: {gsc_data.get('date_range', 'unknown')}

Summary Statistics:
- Total queries in dataset: {len(gsc_data.get('queries', [])):,}
- Total pages in dataset: {len(gsc_data.get('pages', [])):,}
- Total clicks: {summary.get('total_clicks', 0):,}
- Total impressions: {summary.get('total_impressions', 0):,}
- Average CTR: {summary.get('avg_ctr', 0):.2%}
- Average position: {summary.get('avg_position', 0):.2f}

GSC Data (Top 300 queries and pages by clicks):

Top Queries:
{json.dumps(top_queries, indent=2)}

Top Pages:
{json.dumps(top_pages, indent=2)}

You have access to the full dataset with {len(gsc_data.get('queries', []))} queries and {len(gsc_data.get('pages', []))} pages. When answering questions, reference specific data points, queries, pages, and metrics. Be analytical and provide actionable insights. Use specific numbers and examples from the data."""
        
        # Build messages from chat history
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        
        # Try the requested model, fallback to a known working model if it fails
        try:
            response = client.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=8000,
                system=system_message,
                messages=formatted_messages
            )
        except Exception as model_error:
            # If model name is invalid, try a fallback model
            if "model" in str(model_error).lower() or "invalid" in str(model_error).lower():
                st.warning(f"Model 'claude-opus-4-5-20251101' may not be available. Trying fallback model...")
                response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=8000,
                    system=system_message,
                    messages=formatted_messages
                )
            else:
                raise
        
        response_text = response.content[0].text
        # Check stop_reason - it's an attribute of the response object
        stop_reason = getattr(response, 'stop_reason', None)
        
        # Check if response was cut off (max_tokens reached)
        # Also check if response seems incomplete (ends mid-sentence)
        was_cut_off = stop_reason == 'max_tokens' if stop_reason else False
        
        # Additional check: if response doesn't end with punctuation, it might be cut off
        if not was_cut_off and response_text:
            last_char = response_text.strip()[-1] if response_text.strip() else ''
            # If doesn't end with sentence-ending punctuation, might be cut off
            if last_char not in ['.', '!', '?', ':', ';'] and len(response_text) > 1000:
                was_cut_off = True
        
        return response_text, was_cut_off
    except Exception as e:
        error_msg = str(e)
        if "model" in error_msg.lower() or "invalid" in error_msg.lower():
            return f"Error: Invalid model name or API error. Please check your API key and model name. Details: {error_msg}", False
        return f"Error calling Claude API: {error_msg}", False

# Streamlit UI
try:
    st.set_page_config(page_title="GSC Data Analyzer", layout="wide")
except Exception:
    pass  # Page config already set

st.title("Google Search Console Data Analyzer")

# Sidebar
with st.sidebar:
    st.header("Settings")
    
    # Check if API key is loaded
    if st.session_state.claude_api_key:
        st.success("✅ Claude API key loaded from .env")
    else:
        st.error("⚠️ ANTHROPIC_API_KEY not found in .env file")
        st.info("Please add your API key to the .env file:\n`ANTHROPIC_API_KEY=your_key_here`")
    
    st.markdown("---")
    st.markdown("**Note:** Make sure `credentials.json` is in the same directory for GSC authentication.")

# Main interface
domain_input = st.text_input(
    "Domain",
    value=st.session_state.domain,
    placeholder="sc-domain:example.com or https://example.com/",
    help="Enter the exact domain format from Google Search Console"
)

col1, col2 = st.columns([1, 4])
with col1:
    pull_button = st.button("Pull GSC Data", type="primary")

if pull_button:
    if not domain_input:
        st.error("Please enter a domain")
    else:
        st.session_state.domain = domain_input
        with st.spinner("Authenticating and fetching data..."):
            # Authenticate
            creds = authenticate()
            if creds:
                service = build(API_SERVICE_NAME, API_VERSION, credentials=creds)
                
                # Calculate date range (last 90 days)
                end_date = datetime.now()
                start_date = end_date - timedelta(days=90)
                start_str = start_date.strftime('%Y-%m-%d')
                end_str = end_date.strftime('%Y-%m-%d')
                
                # Fetch query data
                query_rows = fetch_gsc_data(service, domain_input, start_str, end_str, ['query'])
                query_data = format_data(query_rows, ['query'])
                
                # Fetch page data
                page_rows = fetch_gsc_data(service, domain_input, start_str, end_str, ['page'])
                page_data = format_data(page_rows, ['page'])
                
                # Calculate summary
                summary = calculate_summary_stats(query_data, page_data)
                
                # Store in session state
                st.session_state.gsc_data = {
                    'queries': query_data,
                    'pages': page_data,
                    'summary': summary,
                    'domain': domain_input,
                    'date_range': f"{start_str} to {end_str}"
                }
                
                st.success("Data loaded successfully!")
            else:
                st.error("Authentication failed")

# Display data if loaded
if st.session_state.gsc_data:
    data = st.session_state.gsc_data
    
    st.markdown("---")
    st.header("Summary Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Clicks", f"{data['summary']['total_clicks']:,}")
    with col2:
        st.metric("Total Impressions", f"{data['summary']['total_impressions']:,}")
    with col3:
        st.metric("Average Position", f"{data['summary']['avg_position']:.2f}")
    with col4:
        st.metric("Average CTR", f"{data['summary']['avg_ctr']:.2%}")
    
    st.caption(f"Data for: {data['domain']} | Date range: {data['date_range']}")
    st.caption(f"Queries: {data['summary']['query_count']:,} | Pages: {data['summary']['page_count']:,}")
    
    # Raw data in expandable sections
    st.markdown("---")
    
    with st.expander("📊 Queries Data (Click to expand)", expanded=False):
        if data['queries']:
            queries_df = pd.DataFrame(data['queries'])
            queries_df = queries_df.sort_values('clicks', ascending=False)
            st.dataframe(queries_df, use_container_width=True, height=400)
        else:
            st.info("No query data available")
    
    with st.expander("📄 Pages Data (Click to expand)", expanded=False):
        if data['pages']:
            pages_df = pd.DataFrame(data['pages'])
            pages_df = pages_df.sort_values('clicks', ascending=False)
            st.dataframe(pages_df, use_container_width=True, height=400)
        else:
            st.info("No page data available")
    
    # Chat interface
    st.markdown("---")
    st.header("💬 Ask Questions About Your GSC Data")
    
    if not st.session_state.claude_api_key:
        st.warning("⚠️ Please set ANTHROPIC_API_KEY in your .env file to use the chat feature.")
    else:
        # Display chat history
        for i, message in enumerate(st.session_state.chat_history):
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        # Chat input
        user_question = st.chat_input("Ask a question about your GSC data...")
        
        if user_question:
            # Add user message to chat
            st.session_state.chat_history.append({
                "role": "user",
                "content": user_question
            })
            
            # Display user message
            with st.chat_message("user"):
                st.markdown(user_question)
            
            # Get response from Claude
            with st.spinner("Analyzing data..."):
                response, was_cut_off = call_claude_api(
                    st.session_state.claude_api_key,
                    st.session_state.chat_history,
                    data
                )
            
            # Add assistant response to chat
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": response
            })
            
            # Store if response was cut off for continue functionality
            st.session_state.last_response_cut_off = was_cut_off
            st.session_state.last_response_text = response
            
            # Display assistant response
            with st.chat_message("assistant"):
                st.markdown(response)
                if was_cut_off:
                    st.info("⚠️ Response may have been cut off due to length limit.")
        
        # Continue button if last response was cut off
        if st.session_state.last_response_cut_off and st.session_state.chat_history:
            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("🔄 Continue", key="continue_button", type="secondary"):
                    # Prepare continue message with previous response as context
                    continue_message = f"Continue from where you left off. Previous response: {st.session_state.last_response_text}"
                    
                    # Create a copy of chat history for the API call (without the continue message)
                    api_chat_history = st.session_state.chat_history.copy()
                    api_chat_history.append({
                        "role": "user",
                        "content": continue_message
                    })
                    
                    # Get continuation from Claude
                    with st.spinner("Continuing response..."):
                        continuation, was_cut_off = call_claude_api(
                            st.session_state.claude_api_key,
                            api_chat_history,
                            data
                        )
                    
                    # Append continuation to last assistant message
                    last_assistant_idx = None
                    for i in range(len(st.session_state.chat_history) - 1, -1, -1):
                        if st.session_state.chat_history[i]["role"] == "assistant":
                            last_assistant_idx = i
                            break
                    
                    if last_assistant_idx is not None:
                        st.session_state.chat_history[last_assistant_idx]["content"] += "\n\n" + continuation
                        st.session_state.last_response_text = st.session_state.chat_history[last_assistant_idx]["content"]
                        st.session_state.last_response_cut_off = was_cut_off
                    else:
                        # If no assistant message found, add as new
                        st.session_state.chat_history.append({
                            "role": "assistant",
                            "content": continuation
                        })
                        st.session_state.last_response_text = continuation
                        st.session_state.last_response_cut_off = was_cut_off
                    
                    st.rerun()
        
        # Clear chat button
        if st.session_state.chat_history:
            if st.button("Clear Chat History"):
                st.session_state.chat_history = []
                st.session_state.last_response_cut_off = False
                st.session_state.last_response_text = ''
                st.rerun()

else:
    st.info("👆 Enter a domain and click 'Pull GSC Data' to get started")
