"""
MENTIONSTACK Content Engine
Production-ready SEO content generation tool
"""

import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
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
if 'domain' not in st.session_state:
    st.session_state.domain = ''
if 'current_tab' not in st.session_state:
    st.session_state.current_tab = 'opportunities'
if 'selected_opportunities' not in st.session_state:
    st.session_state.selected_opportunities = set()
if 'expanded_opportunity' not in st.session_state:
    st.session_state.expanded_opportunity = None
if 'generated_content' not in st.session_state:
    st.session_state.generated_content = []
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'generation_in_progress' not in st.session_state:
    st.session_state.generation_in_progress = False
if 'generation_queue' not in st.session_state:
    st.session_state.generation_queue = []
if 'generation_status' not in st.session_state:
    st.session_state.generation_status = {}
if 'show_confirm_modal' not in st.session_state:
    st.session_state.show_confirm_modal = False
if 'pending_generation' not in st.session_state:
    st.session_state.pending_generation = None
if 'current_article' not in st.session_state:
    st.session_state.current_article = None  # Track which article is being worked on

# ============================================================================
# AUTHENTICATION & DATA FETCHING (PRESERVED)
# ============================================================================

def authenticate():
    """Authenticate with Google Search Console API using Service Account."""
    service_account_info = None
    error_msg = None
    credential_source = None
    
    try:
        if 'GOOGLE_SERVICE_ACCOUNT' in st.secrets:
            service_account_info = st.secrets['GOOGLE_SERVICE_ACCOUNT']
            if not isinstance(service_account_info, dict):
                service_account_info = dict(service_account_info)
            credential_source = "Streamlit secrets"
    except Exception as e:
        error_msg = f"Error reading secrets: {str(e)}"
        service_account_info = None
    
    if service_account_info is None:
        if os.path.exists('service_account.json'):
            try:
                with open('service_account.json', 'r') as f:
                    service_account_info = json.load(f)
                credential_source = "service_account.json file"
            except Exception as e:
                error_msg = f"Error reading service_account.json: {str(e)}"
        else:
            error_msg = "No credentials found in secrets or service_account.json"
    
    if service_account_info is None:
        return None, error_msg or "Credentials not found"
    
    try:
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=SCOPES
        )
        
        # Get the service account email for verification
        sa_email = service_account_info.get('client_email', 'unknown')
        
        # Store credential info in session state for debugging
        if 'credential_info' not in st.session_state:
            st.session_state.credential_info = {
                'source': credential_source,
                'email': sa_email
            }
        
        return creds, None
    except Exception as e:
        return None, f"Error creating credentials: {str(e)}"

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
        rows = response.get('rows', [])
        return rows, None
    except Exception as e:
        error_str = str(e)
        error_type = type(e).__name__
        
        # Get service account email if possible
        sa_email = "gsc-reader@gsc-api-v1-485110.iam.gserviceaccount.com"
        try:
            if hasattr(service, '_http') and hasattr(service._http, 'credentials'):
                sa_email = getattr(service._http.credentials, 'service_account_email', sa_email)
        except:
            pass
        
        # Provide more helpful error messages
        if "403" in error_str or "permission" in error_str.lower() or "forbidden" in error_str.lower():
            return [], f"Permission denied (403). Service account '{sa_email}' needs to be added as a user in Google Search Console for property: {site_url}\n\nFull error: {error_str}"
        elif "404" in error_str or "not found" in error_str.lower():
            return [], f"Property not found (404): {site_url}\n\nThis property doesn't exist or the format is incorrect. Try:\n- 'sc-domain:heatmap.com' (for domain properties)\n- 'https://heatmap.com/' (for URL prefix properties)\n\nFull error: {error_str}"
        elif "400" in error_str or "bad request" in error_str.lower():
            return [], f"Bad request (400): Invalid parameters for {site_url}\n\nPossible issues:\n- Date range is invalid\n- Property format is incorrect\n- API request malformed\n\nFull error: {error_str}"
        else:
            return [], f"Error fetching data ({error_type}): {error_str}\n\nTroubleshooting:\n1. Verify property format matches Search Console exactly\n2. Check service account has access to this property\n3. Ensure date range is valid (last 90 days)\n4. Try refreshing and pulling data again"

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

# ============================================================================
# WEB SCRAPING
# ============================================================================

def scrape_page_content(url):
    """Scrape page content from a URL."""
    try:
        # Set headers to avoid blocking
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Make request with timeout
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract title
        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else None
        
        # Extract meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if not meta_desc:
            meta_desc = soup.find('meta', attrs={'property': 'og:description'})
        meta_description = meta_desc.get('content', '').strip() if meta_desc else None
        
        # Extract meta keywords
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        meta_keywords = meta_keywords.get('content', '').strip() if meta_keywords else None
        
        # Extract Open Graph tags
        og_title = soup.find('meta', attrs={'property': 'og:title'})
        og_title = og_title.get('content', '').strip() if og_title else None
        og_image = soup.find('meta', attrs={'property': 'og:image'})
        og_image = og_image.get('content', '').strip() if og_image else None
        
        # Extract canonical URL
        canonical = soup.find('link', attrs={'rel': 'canonical'})
        canonical_url = canonical.get('href', '') if canonical else None
        
        # Extract schema.org structured data
        schema_data = []
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                schema_json = json.loads(script.string)
                schema_data.append(schema_json)
            except:
                pass
        
        # Extract H1
        h1_tag = soup.find('h1')
        h1 = h1_tag.get_text(strip=True) if h1_tag else None
        
        # Extract all headings (H2-H6)
        headings = []
        for tag in soup.find_all(['h2', 'h3', 'h4', 'h5', 'h6']):
            headings.append({
                'level': tag.name,
                'text': tag.get_text(strip=True)
            })
        
        # Extract body text (main content)
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
            script.decompose()
        
        # Get text from main content areas
        body_text = ""
        main_content = soup.find('main') or soup.find('article') or soup.find('div', class_=lambda x: x and ('content' in x.lower() or 'main' in x.lower() or 'post' in x.lower()))
        
        if main_content:
            body_text = main_content.get_text(separator=' ', strip=True)
        else:
            # Fallback to body tag
            body = soup.find('body')
            if body:
                body_text = body.get_text(separator=' ', strip=True)
        
        # Limit body text length (first 5000 chars)
        if body_text:
            body_text = body_text[:5000] + "..." if len(body_text) > 5000 else body_text
        
        return {
            'url': url,
            'title': title,
            'meta_description': meta_description,
            'meta_keywords': meta_keywords,
            'og_title': og_title,
            'og_image': og_image,
            'canonical_url': canonical_url,
            'h1': h1,
            'headings': headings,
            'body_text': body_text,
            'schema_data': schema_data,
            'scraped_at': datetime.now().isoformat(),
            'status': 'success'
        }
    except requests.exceptions.RequestException as e:
        return {
            'url': url,
            'status': 'error',
            'error': f"Request error: {str(e)}"
        }
    except Exception as e:
        return {
            'url': url,
            'status': 'error',
            'error': f"Scraping error: {str(e)}"
        }

def scrape_top_pages(pages_data, max_pages=20):
    """Scrape content from top pages by clicks."""
    if not pages_data:
        return []
    
    # Sort by clicks and take top pages
    sorted_pages = sorted(pages_data, key=lambda x: x.get('clicks', 0), reverse=True)
    top_pages = sorted_pages[:max_pages]
    
    scraped_content = []
    
    for page in top_pages:
        url = page.get('page', '')
        if not url:
            continue
        
        # Ensure URL is absolute
        if url.startswith('/'):
            # If relative URL, we need the domain - skip for now or use domain from GSC data
            continue
        
        # Scrape the page
        content = scrape_page_content(url)
        # Merge with GSC metrics
        content.update({
            'clicks': page.get('clicks', 0),
            'impressions': page.get('impressions', 0),
            'ctr': page.get('ctr', 0),
            'position': page.get('position', 0)
        })
        scraped_content.append(content)
        
        # Small delay to be respectful
        time.sleep(0.5)
    
    return scraped_content

# ============================================================================
# OPPORTUNITY SCORING
# ============================================================================

def calculate_opportunity_score(row):
    """Calculate opportunity score 1-100 based on position, impressions, and CTR."""
    score = 0
    position = row.get('position', 100)
    impressions = row.get('impressions', 0)
    actual_ctr = row.get('ctr', 0)
    
    # Position scoring
    if 4 <= position <= 10:
        score += 35
    elif 11 <= position <= 15:
        score += 28
    elif 1 <= position <= 3:
        score += 15
    elif 16 <= position <= 30:
        score += 20
    else:
        score += 10
    
    # Impressions scoring
    if impressions >= 10000:
        score += 30
    elif impressions >= 5000:
        score += 25
    elif impressions >= 1000:
        score += 18
    elif impressions >= 500:
        score += 12
    else:
        score += 5
    
    # CTR scoring
    expected_ctr = {
        1: 0.28, 2: 0.15, 3: 0.11, 4: 0.08, 5: 0.07,
        6: 0.05, 7: 0.04, 8: 0.035, 9: 0.03, 10: 0.025
    }.get(int(position), 0.02)
    
    if actual_ctr < expected_ctr * 0.5:
        score += 25
    elif actual_ctr < expected_ctr * 0.75:
        score += 18
    elif actual_ctr < expected_ctr:
        score += 10
    else:
        score += 5
    
    return min(score, 100)

def prepare_opportunities(gsc_data):
    """Prepare opportunities from GSC data with scoring."""
    if not gsc_data:
        return []
    
    opportunities = []
    
    # Process queries
    for query_row in gsc_data.get('queries', []):
        if query_row.get('impressions', 0) >= 100:  # Minimum threshold
            opportunities.append({
                'id': f"query_{query_row['query']}",
                'type': 'NEW',
                'keyword': query_row['query'],
                'page': None,
                'position': query_row['position'],
                'impressions': query_row['impressions'],
                'ctr': query_row['ctr'],
                'clicks': query_row['clicks'],
                'score': calculate_opportunity_score(query_row)
            })
    
    # Process pages
    for page_row in gsc_data.get('pages', []):
        if page_row.get('impressions', 0) >= 100:
            page_url = page_row['page']
            # Extract keyword from URL or use page title
            keyword = page_url.split('/')[-1].replace('-', ' ').title()
            opportunities.append({
                'id': f"page_{page_url}",
                'type': 'REFRESH',
                'keyword': keyword,
                'page': page_url,
                'position': page_row['position'],
                'impressions': page_row['impressions'],
                'ctr': page_row['ctr'],
                'clicks': page_row['clicks'],
                'score': calculate_opportunity_score(page_row)
            })
    
    # Sort by score descending and take top 25
    opportunities.sort(key=lambda x: x['score'], reverse=True)
    return opportunities[:25]

# ============================================================================
# CONTENT GENERATION
# ============================================================================

def generate_content_brief(opportunity, custom_brief=""):
    """Generate a brief for content generation using Claude."""
    keyword = opportunity['keyword']
    opp_type = opportunity['type']
    position = opportunity['position']
    impressions = opportunity['impressions']
    ctr = opportunity['ctr']
    page_url = opportunity.get('page', '')
    
    brief = f"""Generate SEO-optimized content for this opportunity:

Keyword: {keyword}
Type: {opp_type}
Current Position: {position}
Impressions: {impressions:,}
Current CTR: {ctr:.2%}
Target URL: {page_url if page_url else 'New page needed'}

"""
    if custom_brief:
        brief += f"Additional Instructions: {custom_brief}\n\n"
    
    if opp_type == 'REFRESH':
        brief += """This is a REFRESH opportunity. Update existing content:
- Maintain core topic and URL
- Update outdated statistics and references to 2026
- Strengthen weak sections
- Improve structure if needed
"""
    else:
        brief += """This is a NEW content opportunity. Create comprehensive content:
- Be the best resource on this keyword
- Include unique angles competitors miss
"""
    
    return brief

def call_claude_for_content(api_key, brief):
    """Call Claude API to generate content."""
    if not api_key:
        return None, "API key not configured"
    
    try:
        client = Anthropic(api_key=api_key)
        
        system_prompt = """You are an expert SEO content writer for a health and wellness brand. Generate high-quality, publication-ready content.

CONTENT REQUIREMENTS
Structure:
- Open with a compelling hook that addresses the reader's core problem or desire
- First paragraph must contain a standalone, quotable definition or key insight (citation hook for AI systems)
- Use clear H2 subheadings that match search intent (not clever, but clear)
- Include an FAQ section with 3-5 questions based on "People Also Ask"
- End with a clear next step or CTA

Formatting:
- Output valid HTML with proper tags: <h1>, <h2>, <p>, <ul>, <li>, <a>
- Include 3-5 internal links using <a href="/page-slug">anchor text</a> format
- Include 1-2 external links to authoritative sources
- Target 1,500-2,000 words for comprehensive guides
- Target 800-1,200 words for focused articles

Tone:
- Expert but accessible
- Confident, not hedging
- Use "you" to address the reader directly
- Avoid fluff and filler phrases

SEO Elements:
- Title tag: Under 60 characters, includes primary keyword naturally
- Meta description: 150-160 characters, compelling and includes keyword
- H1: Can differ slightly from title tag, but aligned

Output format:
Provide your response as JSON with these keys:
{
  "title_tag": "...",
  "meta_description": "...",
  "content": "<h1>...</h1><p>...</p>..."
}"""
        
        response = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=8000,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": brief
            }]
        )
        
        response_text = response.content[0].text
        
        # Try to parse as JSON
        try:
            # Extract JSON from response (might have markdown code blocks)
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            
            content_data = json.loads(response_text)
            return content_data, None
        except:
            # If JSON parsing fails, create structure from text
            return {
                "title_tag": brief.split('\n')[0].replace('Keyword: ', ''),
                "meta_description": response_text[:160],
                "content": response_text
            }, None
            
    except Exception as e:
        return None, str(e)

def generate_opportunity_analysis(api_key, opportunity):
    """Generate why and recommended approach for an opportunity."""
    if not api_key:
        return "Analysis unavailable", "Configure API key to see recommendations"
    
    try:
        client = Anthropic(api_key=api_key)
        
        prompt = f"""Analyze this SEO opportunity and provide:
1. Why this is a good opportunity (2-3 bullet points)
2. Recommended approach (3-4 actionable steps)

Opportunity:
- Keyword: {opportunity['keyword']}
- Type: {opportunity['type']}
- Position: {opportunity['position']}
- Impressions: {opportunity['impressions']:,}
- CTR: {opportunity['ctr']:.2%}
- Score: {opportunity['score']}/100

Be specific and actionable. Reference the actual numbers."""
        
        response = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        analysis = response.content[0].text
        
        # Split into why and approach
        if "Recommended" in analysis or "Approach" in analysis:
            parts = analysis.split("Recommended", 1)
            why = parts[0].strip()
            approach = "Recommended" + parts[1] if len(parts) > 1 else ""
        else:
            why = analysis
            approach = "See recommendations above."
        
        return why, approach
    except:
        return "Analysis unavailable", "Error generating analysis"

# ============================================================================
# STYLING & UI HELPERS
# ============================================================================

def apply_custom_css():
    """Apply custom CSS for brand styling."""
    st.markdown("""
    <style>
    /* Brand Colors */
    :root {
        --primary-purple: #6B46C1;
        --light-purple: #F3E8FF;
        --white: #FFFFFF;
        --black: #1A1A1A;
        --gray: #6B7280;
        --green-bg: #10B981;
        --green-text: #065F46;
        --orange-bg: #F59E0B;
        --orange-text: #92400E;
        --red: #EF4444;
    }
    
    /* Main container */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Headers */
    h1, h2, h3 {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: var(--black);
    }
    
    /* Buttons */
    .stButton > button {
        border-radius: 6px;
        font-weight: 500;
    }
    
    /* Selected row styling */
    .selected-row {
        background-color: var(--light-purple) !important;
    }
    
    /* Badges */
    .badge-new {
        background-color: var(--green-bg);
        color: var(--green-text);
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
    }
    
    .badge-refresh {
        background-color: var(--orange-bg);
        color: var(--orange-text);
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
    }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# MAIN UI
# ============================================================================

# Page config
st.set_page_config(
    page_title="MENTIONSTACK Content Engine",
    layout="wide",
    initial_sidebar_state="collapsed"
)

apply_custom_css()

# Header
col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    st.markdown("### <span style='color: #6B46C1; font-weight: bold;'>◆ MENTIONSTACK</span>", unsafe_allow_html=True)
    st.markdown("<span style='color: #6B7280; font-size: 14px;'>Content Engine</span>", unsafe_allow_html=True)
with col3:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.session_state.gsc_data = None
        st.session_state.selected_opportunities = set()
        st.rerun()

st.markdown("---")

# Tab Navigation
tab1, tab2 = st.tabs(["📊 Opportunities", "📝 Generated Content"])

# ============================================================================
# TAB 1: OPPORTUNITIES
# ============================================================================

with tab1:
    # Domain input (if no data loaded)
    if not st.session_state.gsc_data:
        st.markdown("### Connect Your Search Console Data")
        domain_input = st.text_input(
            "Domain",
            value=st.session_state.domain,
            placeholder="sc-domain:example.com or https://example.com/",
            help="Enter the exact domain format from Google Search Console. For 'heatmap.com' property, use 'sc-domain:heatmap.com'"
        )
        
        # Helper text for common issues
        if domain_input and domain_input.startswith('https://'):
            st.info("💡 **Tip:** If your property shows as 'heatmap.com' (not 'https://heatmap.com/'), try using `sc-domain:heatmap.com` instead")
        
        if st.button("Pull GSC Data", type="primary", use_container_width=True):
            if not domain_input:
                st.error("Please enter a domain")
            else:
                st.session_state.domain = domain_input
                with st.status("Connecting to Search Console...", expanded=True) as status:
                    status.update(label="Connecting to Search Console...", state="running")
                    time.sleep(0.5)
                    
                    creds, auth_error = authenticate()
                    if not creds:
                        status.update(label="❌ Authentication failed", state="error")
                        error_details = auth_error or "Unknown authentication error"
                        
                        # Show which credentials are being used
                        cred_info = st.session_state.get('credential_info', {})
                        cred_source = cred_info.get('source', 'Unknown')
                        cred_email = cred_info.get('email', 'Unknown')
                        
                        st.error(f"""
**Couldn't connect to Search Console.**

**Error:** {error_details}

**Credential Source:** {cred_source}
**Service Account Email:** {cred_email}

**For local development:**
1. Check `.streamlit/secrets.toml` - make sure it has the SAME credentials as Streamlit Cloud
2. Verify the `client_email` in secrets matches: `gsc-reader@gsc-api-v1-485110.iam.gserviceaccount.com`
3. If using `service_account.json`, make sure it's the same file

**Important:** The service account email must match exactly. If your local secrets have different credentials than Streamlit Cloud, that's why it works in one place but not the other.
                        """)
                    else:
                        service = build(API_SERVICE_NAME, API_VERSION, credentials=creds)
                        
                        status.update(label="Pulling your data...", state="running")
                        time.sleep(0.5)
                        
                        end_date = datetime.now()
                        start_date = end_date - timedelta(days=90)
                        start_str = start_date.strftime('%Y-%m-%d')
                        end_str = end_date.strftime('%Y-%m-%d')
                        
                        # Show which service account is being used
                        try:
                            sa_email = creds.service_account_email
                            st.info(f"🔐 Using service account: `{sa_email}`")
                        except:
                            pass
                        
                        # List available sites BEFORE trying to fetch
                        try:
                            sites_list = service.sites().list().execute()
                            available_sites = [site.get('siteUrl', '') for site in sites_list.get('siteEntry', [])]
                            if available_sites:
                                st.info(f"""
**Available properties for this service account:**
{chr(10).join(f"- `{site}`" for site in available_sites[:15])}

**You're trying:** `{domain_input}`
**Match found:** {'✅ Yes' if domain_input in available_sites else '❌ No - Use one of the formats above'}
                                """)
                        except Exception as list_error:
                            st.warning(f"Could not list available sites: {str(list_error)}")
                        
                        status.update(label="Fetching query data...", state="running")
                        query_rows, query_error = fetch_gsc_data(service, domain_input, start_str, end_str, ['query'])
                        
                        if query_error:
                            status.update(label="❌ Error fetching queries", state="error")
                            st.error(f"**Query Data Error:** {query_error}")
                            
                            # Provide helpful troubleshooting
                            st.markdown("""
                            **Troubleshooting Steps:**
                            
                            1. **Check the available properties above** - Use the EXACT format shown
                            
                            2. **Verify service account is added to THIS property:**
                               - In Search Console, select the property
                               - Go to Settings → Users and permissions
                               - Verify `gsc-reader@gsc-api-v1-485110.iam.gserviceaccount.com` is listed
                               - If not, add it with "Full" access
                            
                            3. **Wait 2-5 minutes** after adding the service account (permissions need time to propagate)
                            
                            4. **Check the full error message above** for specific details
                            """)
                            st.stop()
                        
                        query_data = format_data(query_rows, ['query'])
                        
                        status.update(label="Fetching page data...", state="running")
                        page_rows, page_error = fetch_gsc_data(service, domain_input, start_str, end_str, ['page'])
                        
                        if page_error:
                            status.update(label="❌ Error fetching pages", state="error")
                            st.error(f"**Page Data Error:** {page_error}")
                            st.stop()
                        
                        page_data = format_data(page_rows, ['page'])
                        
                        # Check if we got any data
                        if not query_data and not page_data:
                            status.update(label="⚠️ No data found", state="error")
                            st.warning(f"""
**No data returned for {domain_input}**

Possible reasons:
1. No search data in the last 90 days
2. Service account doesn't have access to this property
3. Domain format is incorrect

**To fix:**
- Verify the domain format (try both `sc-domain:example.com` and `https://example.com/`)
- Check that the service account email is added as a user in Google Search Console
- Try a different date range or property
                            """)
                            st.stop()
                        
                        status.update(label="Ranking by ROI potential...", state="running")
                        time.sleep(0.5)
                        
                        # Scrape top pages content
                        scraped_pages = []
                        if page_data:
                            status.update(label="Scraping top pages content...", state="running")
                            with st.spinner("Fetching page content (this may take a minute)..."):
                                scraped_pages = scrape_top_pages(page_data, max_pages=20)
                        
                        st.session_state.gsc_data = {
                            'queries': query_data,
                            'pages': page_data,
                            'scraped_pages': scraped_pages,  # Add scraped content
                            'domain': domain_input,
                            'date_range': f"{start_str} to {end_str}"
                        }
                        
                        total_opps = len(query_data) + len(page_data)
                        scraped_count = len([p for p in scraped_pages if p.get('status') == 'success'])
                        status.update(label=f"Done! Found {total_opps} data points. Scraped {scraped_count} pages.", state="complete")
                        st.rerun()
    else:
        # Opportunities table
        st.markdown("### TOP 25 CONTENT OPPORTUNITIES")
        st.markdown("<span style='color: #6B7280;'>Ranked by ROI potential based on your GSC data</span>", unsafe_allow_html=True)
        
        opportunities = prepare_opportunities(st.session_state.gsc_data)
        
        if not opportunities:
            st.info("No opportunities found. Try pulling data for a different domain.")
        else:
            # Selection controls
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                selected_count = len(st.session_state.selected_opportunities)
                st.markdown(f"**Selected: {selected_count} of {len(opportunities)}**")
            with col2:
                if st.button("Select Top 10", use_container_width=True):
                    top_10_ids = [opp['id'] for opp in opportunities[:10]]
                    st.session_state.selected_opportunities = set(top_10_ids)
                    st.rerun()
            with col3:
                if st.button("Generate Selected", type="primary", use_container_width=True, disabled=selected_count == 0):
                    selected_opps = [
                        opp for opp in opportunities 
                        if opp['id'] in st.session_state.selected_opportunities
                    ]
                    st.session_state.pending_generation = selected_opps
                    st.session_state.show_confirm_modal = True
                    st.rerun()
            
            st.markdown("---")
            
            # Table header
            header_cols = st.columns([0.5, 1, 2, 1.5, 1.5, 1, 1, 1])
            with header_cols[0]:
                st.markdown("")
            with header_cols[1]:
                st.markdown("**#**")
            with header_cols[2]:
                st.markdown("**Type | Keyword/Page**")
            with header_cols[3]:
                st.markdown("**Position**")
            with header_cols[4]:
                st.markdown("**Impressions**")
            with header_cols[5]:
                st.markdown("**CTR**")
            with header_cols[6]:
                st.markdown("**Score**")
            with header_cols[7]:
                st.markdown("**Action**")
            
            st.markdown("---")
            
            # Opportunities table
            for idx, opp in enumerate(opportunities, 1):
                is_selected = opp['id'] in st.session_state.selected_opportunities
                is_expanded = st.session_state.expanded_opportunity == opp['id']
                
                # Row container
                row_style = "background-color: #F3E8FF; padding: 12px; border-radius: 6px; margin-bottom: 8px;" if is_selected else "padding: 12px; border: 1px solid #E5E7EB; border-radius: 6px; margin-bottom: 8px;"
                
                with st.container():
                    cols = st.columns([0.5, 1, 2, 1.5, 1.5, 1, 1, 1])
                    
                    with cols[0]:
                        checkbox_key = f"select_{opp['id']}"
                        checkbox_value = st.checkbox("", value=is_selected, key=checkbox_key, label_visibility="collapsed")
                        if checkbox_value != is_selected:
                            if checkbox_value:
                                st.session_state.selected_opportunities.add(opp['id'])
                            else:
                                st.session_state.selected_opportunities.discard(opp['id'])
                            st.rerun()
                    
                    with cols[1]:
                        st.markdown(f"**{idx}**")
                    
                    with cols[2]:
                        badge_class = "badge-new" if opp['type'] == 'NEW' else "badge-refresh"
                        badge_text = "NEW" if opp['type'] == 'NEW' else "REFRESH"
                        badge_color = "#10B981" if opp['type'] == 'NEW' else "#F59E0B"
                        st.markdown(f"<span style='background-color: {badge_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;'>{badge_text}</span>", unsafe_allow_html=True)
                        keyword_display = opp['keyword'][:40] + "..." if len(opp['keyword']) > 40 else opp['keyword']
                        st.markdown(f"<span style='margin-left: 8px;'>{keyword_display}</span>", unsafe_allow_html=True)
                    
                    with cols[3]:
                        pos = opp['position']
                        st.markdown(f"{pos:.1f}" if pos > 0 else "--")
                    
                    with cols[4]:
                        imp = opp['impressions']
                        imp_str = f"{imp/1000:.1f}K" if imp >= 1000 else str(int(imp))
                        st.markdown(imp_str)
                    
                    with cols[5]:
                        st.markdown(f"{opp['ctr']:.1%}")
                    
                    with cols[6]:
                        st.markdown(f"**{opp['score']}**")
                    
                    with cols[7]:
                        expand_key = f"expand_{opp['id']}"
                        if st.button("View", key=expand_key, use_container_width=True):
                            if st.session_state.expanded_opportunity == opp['id']:
                                st.session_state.expanded_opportunity = None
                            else:
                                st.session_state.expanded_opportunity = opp['id']
                            st.rerun()
                
                # Expanded details
                if is_expanded:
                    with st.expander("", expanded=True):
                        st.markdown("#### WHY THIS OPPORTUNITY?")
                        
                        # Generate analysis
                        why, approach = generate_opportunity_analysis(
                            st.session_state.claude_api_key,
                            opp
                        )
                        
                        st.markdown(why)
                        st.markdown("---")
                        st.markdown("#### RECOMMENDED APPROACH")
                        st.markdown(approach)
                        st.markdown("---")
                        
                        st.markdown(f"**Target Keyword:** {opp['keyword']}")
                        if opp.get('page'):
                            st.markdown(f"**Current URL:** {opp['page']} [Open ↗]({opp['page']})")
                        else:
                            st.markdown("**Current URL:** New page needed")
                        
                        st.markdown("---")
                        st.text_area("Edit Brief (optional):", key=f"brief_{opp['id']}", height=100)

# ============================================================================
# TAB 2: GENERATED CONTENT
# ============================================================================

with tab2:
    st.markdown("### GENERATED CONTENT")
    st.markdown("<span style='color: #6B7280;'>Your previously generated articles</span>", unsafe_allow_html=True)
    
    if not st.session_state.generated_content:
        st.markdown("""
        <div style='text-align: center; padding: 60px 20px;'>
            <div style='font-size: 48px; margin-bottom: 20px;'>📝</div>
            <h3 style='color: #1A1A1A; margin-bottom: 10px;'>No content generated yet</h3>
            <p style='color: #6B7280; margin-bottom: 30px;'>Select opportunities and generate your first article</p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("Go to Opportunities", type="primary", use_container_width=True):
            st.session_state.current_tab = 'opportunities'
            st.rerun()
    else:
        # Content list
        for content in st.session_state.generated_content:
            with st.expander(f"{content['title']} | {content['type']} | {content['date']}", expanded=False):
                col1, col2 = st.columns([1, 1])
                with col1:
                    status_idx = 0 if content.get('status') == 'Draft' else 1
                    new_status = st.selectbox("Status", ["Draft", "Sent"], key=f"status_{content['id']}", index=status_idx)
                    if new_status != content.get('status'):
                        content['status'] = new_status
                with col2:
                    col2a, col2b = st.columns(2)
                    with col2a:
                        if st.button("📋 Copy", key=f"copy_{content['id']}", use_container_width=True):
                            st.session_state[f"show_copy_{content['id']}"] = True
                    
                    if st.session_state.get(f"show_copy_{content['id']}", False):
                        full_content = f"{content['title_tag']}\n\n{content['meta_description']}\n\n{content['content']}"
                        st.text_area("Copy this content:", value=full_content, height=200, key=f"copy_area_{content['id']}")
                        st.info("Select all (Cmd/Ctrl+A) and copy (Cmd/Ctrl+C) to copy the content")
                    with col2b:
                        if st.button("🔄 Redo", key=f"redo_{content['id']}", use_container_width=True):
                            st.info("Redo functionality coming soon")
                
                st.markdown("**TITLE TAG**")
                st.code(content['title_tag'], language=None)
                
                st.markdown("**META DESCRIPTION**")
                st.code(content['meta_description'], language=None)
                
                st.markdown("**ARTICLE CONTENT**")
                st.code(content['content'], language='html')

# ============================================================================
# CONFIRMATION MODAL
# ============================================================================

if st.session_state.show_confirm_modal and st.session_state.pending_generation:
    st.markdown("---")
    with st.container():
        st.markdown("### Generate articles?")
        st.markdown(f"This will create content for **{len(st.session_state.pending_generation)}** article(s):")
        
        for opp in st.session_state.pending_generation:
            badge_text = "Refresh" if opp['type'] == 'REFRESH' else "New"
            badge_color = "#F59E0B" if opp['type'] == 'REFRESH' else "#10B981"
            st.markdown(f"• {opp['keyword']} <span style='background-color: {badge_color}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px;'>{badge_text}</span>", unsafe_allow_html=True)
        
        st.markdown(f"\n**Estimated time:** ~{len(st.session_state.pending_generation) * 2}-{len(st.session_state.pending_generation) * 3} minutes")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("Cancel", use_container_width=True):
                st.session_state.show_confirm_modal = False
                st.session_state.pending_generation = None
                st.rerun()
        with col2:
            if st.button("Generate", type="primary", use_container_width=True):
                st.session_state.generation_queue = st.session_state.pending_generation
                st.session_state.generation_in_progress = True
                st.session_state.show_confirm_modal = False
                st.session_state.pending_generation = None
                st.session_state.current_tab = 'generated'
                st.rerun()

# ============================================================================
# GENERATION PROGRESS (if in progress)
# ============================================================================

if st.session_state.generation_in_progress and st.session_state.generation_queue:
    st.markdown("---")
    st.markdown("### GENERATING CONTENT")
    
    total = len(st.session_state.generation_queue)
    completed = len([s for s in st.session_state.generation_status.values() if s == 'completed'])
    current_idx = completed
    
    progress = completed / total if total > 0 else 0
    st.progress(progress)
    st.markdown(f"**{completed} of {total}** ({int(progress * 100)}%)")
    
    for idx, opp in enumerate(st.session_state.generation_queue):
        status = st.session_state.generation_status.get(opp['id'], 'pending')
        
        if status == 'completed':
            st.markdown(f"✓ {opp['keyword']}")
            st.caption("Done! Ready to review.")
        elif status == 'generating':
            st.markdown(f"◆ {opp['keyword']}")
            current_msg = st.session_state.generation_status.get(f"{opp['id']}_msg", "Crafting content...")
            st.caption(current_msg)
        else:
            st.markdown(f"○ {opp['keyword']}")
    
    # Process generation sequentially
    if current_idx < total:
        current_opp = st.session_state.generation_queue[current_idx]
        status = st.session_state.generation_status.get(current_opp['id'], 'pending')
        
        if status == 'pending':
            # Start generating this one
            st.session_state.generation_status[current_opp['id']] = 'generating'
            st.session_state.generation_status[f"{current_opp['id']}_msg"] = "Analyzing search intent..."
            st.rerun()
        elif status == 'generating':
            # Check if we've already started generating (to avoid multiple calls)
            if f"{current_opp['id']}_started" not in st.session_state.generation_status:
                # Mark as started
                st.session_state.generation_status[f"{current_opp['id']}_started"] = True
                st.session_state.generation_status[f"{current_opp['id']}_msg"] = "Analyzing search intent..."
                st.rerun()
            else:
                # Generate content (this will take time)
                st.session_state.generation_status[f"{current_opp['id']}_msg"] = "Crafting compelling intro..."
                brief = generate_content_brief(current_opp)
                content_data, error = call_claude_for_content(st.session_state.claude_api_key, brief)
                
                if content_data and not error:
                    # Save generated content
                    new_content = {
                        'id': f"content_{len(st.session_state.generated_content)}",
                        'title': current_opp['keyword'],
                        'type': current_opp['type'],
                        'date': datetime.now().strftime("%b %d, %Y"),
                        'status': 'Draft',
                        'title_tag': content_data.get('title_tag', current_opp['keyword']),
                        'meta_description': content_data.get('meta_description', ''),
                        'content': content_data.get('content', '')
                    }
                    st.session_state.generated_content.append(new_content)
                    st.session_state.generation_status[current_opp['id']] = 'completed'
                    # Clean up
                    if f"{current_opp['id']}_started" in st.session_state.generation_status:
                        del st.session_state.generation_status[f"{current_opp['id']}_started"]
                else:
                    st.session_state.generation_status[current_opp['id']] = 'error'
                    st.session_state.generation_status[f"{current_opp['id']}_error"] = error or "Generation failed"
                    # Clean up
                    if f"{current_opp['id']}_started" in st.session_state.generation_status:
                        del st.session_state.generation_status[f"{current_opp['id']}_started"]
                
                st.rerun()
        elif status == 'error':
            # Show error with retry option
            error_msg = st.session_state.generation_status.get(f"{current_opp['id']}_error", "Generation failed")
            st.markdown(f"✗ {current_opp['keyword']}")
            st.caption(f"Error: {error_msg}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Retry", key=f"retry_{current_opp['id']}"):
                    st.session_state.generation_status[current_opp['id']] = 'pending'
                    st.rerun()
            with col2:
                if st.button("Skip", key=f"skip_{current_opp['id']}"):
                    st.session_state.generation_status[current_opp['id']] = 'skipped'
                    st.rerun()
    else:
        # All done
        st.session_state.generation_in_progress = False
        st.session_state.generation_queue = []
        st.session_state.generation_status = {}
        st.success("✅ All content generated!")
        time.sleep(2)
        st.rerun()

# ============================================================================
# CHAT SECTION (Fixed at bottom)
# ============================================================================

st.markdown("---")
st.markdown("### 💬 Ask anything or request changes")

# Show current article being worked on
if st.session_state.current_article:
    current = st.session_state.current_article
    st.info(f"📝 **Currently working on:** {current.get('title', 'Unknown')} - {current.get('url', '')}")

# Display chat history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat input
user_input = st.chat_input("Type your message...")

if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    
    # Call Claude for chat response
    if st.session_state.claude_api_key:
        try:
            client = Anthropic(api_key=st.session_state.claude_api_key)
            
            # Function to match semantic article names to scraped pages
            def find_article_by_name(name, scraped_pages):
                """Match semantic article name to a scraped page."""
                if not scraped_pages:
                    return None
                
                name_lower = name.lower()
                best_match = None
                best_score = 0
                
                for page in scraped_pages:
                    if page.get('status') != 'success':
                        continue
                    
                    # Check title
                    title = (page.get('title') or '').lower()
                    h1 = (page.get('h1') or '').lower()
                    url = (page.get('url') or '').lower()
                    
                    # Score based on keyword matches
                    score = 0
                    name_words = name_lower.split()
                    
                    for word in name_words:
                        if word in title:
                            score += 3
                        if word in h1:
                            score += 2
                        if word in url:
                            score += 1
                    
                    # Exact match bonus
                    if name_lower in title or name_lower in h1:
                        score += 10
                    
                    if score > best_score:
                        best_score = score
                        best_match = page
                
                return best_match if best_score > 0 else None
            
            # Check if user is asking about a specific article
            current_article = st.session_state.current_article
            article_mentioned = None
            
            # Try to find article by semantic name or URL in user input
            if st.session_state.gsc_data and st.session_state.gsc_data.get('scraped_pages'):
                scraped_pages = st.session_state.gsc_data.get('scraped_pages', [])
                
                # Check for URL in input
                for page in scraped_pages:
                    if page.get('url') and page.get('url') in user_input:
                        article_mentioned = page
                        break
                
                # If no URL match, try semantic matching
                if not article_mentioned:
                    # Look for common patterns like "PU leather guide", "rewrite the article about X"
                    rewrite_keywords = ['rewrite', 'edit', 'update', 'improve', 'article about', 'guide', 'post']
                    if any(keyword in user_input.lower() for keyword in rewrite_keywords):
                        # Extract potential article name
                        # Simple extraction - look for phrases after keywords
                        for keyword in ['about', 'guide', 'article', 'the']:
                            if keyword in user_input.lower():
                                parts = user_input.lower().split(keyword, 1)
                                if len(parts) > 1:
                                    potential_name = parts[1].strip().split('.')[0].split('?')[0].strip()
                                    if len(potential_name) > 3:  # Only if meaningful
                                        article_mentioned = find_article_by_name(potential_name, scraped_pages)
                                        if article_mentioned:
                                            break
                
                # If still no match but we have a current article, use that
                if not article_mentioned and current_article:
                    # Find current article in scraped pages
                    for page in scraped_pages:
                        if page.get('url') == current_article.get('url'):
                            article_mentioned = page
                            break
            
            # Update current article if one was mentioned
            if article_mentioned:
                st.session_state.current_article = article_mentioned
            
            # Use current article if no new one mentioned
            if not article_mentioned and current_article:
                article_mentioned = current_article
            
            # Build context from GSC data
            context_parts = []
            
            if st.session_state.gsc_data:
                gsc_data = st.session_state.gsc_data
                domain = gsc_data.get('domain', 'unknown')
                date_range = gsc_data.get('date_range', 'unknown')
                queries = gsc_data.get('queries', [])
                pages = gsc_data.get('pages', [])
                scraped_pages = gsc_data.get('scraped_pages', [])
                
                # Get top performing queries
                top_queries = sorted(queries, key=lambda x: x.get('clicks', 0), reverse=True)[:20]
                
                # Build pages context with scraped content (full details for current article, summary for others)
                pages_context = []
                current_article_url = article_mentioned.get('url') if article_mentioned else None
                
                if scraped_pages:
                    for page in scraped_pages[:20]:  # Top 20 scraped pages
                        if page.get('status') == 'success':
                            # Full details for current article, summary for others
                            if page.get('url') == current_article_url:
                                pages_context.append({
                                    'url': page.get('url'),
                                    'title': page.get('title'),
                                    'meta_description': page.get('meta_description'),
                                    'meta_keywords': page.get('meta_keywords'),
                                    'og_title': page.get('og_title'),
                                    'canonical_url': page.get('canonical_url'),
                                    'h1': page.get('h1'),
                                    'headings': page.get('headings', []),  # Full headings list
                                    'body_text': page.get('body_text'),  # Full body text
                                    'schema_data': page.get('schema_data', []),
                                    'clicks': page.get('clicks', 0),
                                    'impressions': page.get('impressions', 0),
                                    'ctr': page.get('ctr', 0),
                                    'position': page.get('position', 0),
                                    'is_current_article': True
                                })
                            else:
                                # Summary for other pages
                                pages_context.append({
                                    'url': page.get('url'),
                                    'title': page.get('title'),
                                    'meta_description': page.get('meta_description'),
                                    'h1': page.get('h1'),
                                    'headings_count': len(page.get('headings', [])),
                                    'body_preview': page.get('body_text', '')[:300] if page.get('body_text') else None,
                                    'clicks': page.get('clicks', 0),
                                    'impressions': page.get('impressions', 0),
                                    'ctr': page.get('ctr', 0),
                                    'position': page.get('position', 0)
                                })
                        else:
                            # Include pages that failed to scrape but have GSC data
                            pages_context.append({
                                'url': page.get('url'),
                                'clicks': page.get('clicks', 0),
                                'impressions': page.get('impressions', 0),
                                'ctr': page.get('ctr', 0),
                                'position': page.get('position', 0),
                                'scrape_status': 'failed',
                                'error': page.get('error', 'Unknown error')
                            })
                else:
                    # Fallback to pages without scraped content
                    top_pages = sorted(pages, key=lambda x: x.get('clicks', 0), reverse=True)[:20]
                    pages_context = top_pages
                
                # Add note about current article if one is selected
                if article_mentioned:
                    context_parts.append(f"""
**CURRENT ARTICLE BEING WORKED ON:**
- URL: {article_mentioned.get('url')}
- Title: {article_mentioned.get('title')}
- This is the article you should focus on for rewrites and edits unless the user explicitly mentions a different article.
""")
                
                # Calculate scraped count outside f-string to avoid syntax issues
                scraped_count = len([p for p in scraped_pages if p.get('status') == 'success'])
                
                context_parts.append(f"""
**Google Search Console Data Context:**
- Domain: {domain}
- Date Range: {date_range}
- Total Queries: {len(queries)}
- Total Pages: {len(pages)}
- Pages Scraped: {scraped_count}

**Top Performing Queries (by clicks):**
{json.dumps(top_queries, indent=2) if top_queries else "No query data"}

**Top Performing Pages with Content Analysis:**
{json.dumps(pages_context, indent=2) if pages_context else "No page data"}

**Note:** Pages include scraped content (title, meta description, headings, body text) when available, allowing for content quality analysis alongside traffic metrics.
""")
            
            # Add generated content context
            if st.session_state.generated_content:
                context_parts.append("\n**Generated Content:**\n")
                for content in st.session_state.generated_content[-5:]:  # Last 5 items
                    context_parts.append(f"- {content['title']} ({content['type']}) - {content['date']}\n")
            
            # Build full context
            context = "\n".join(context_parts) if context_parts else ""
            
            # Create system message
            system_message = """You are an SEO content writer and analyst assistant helping with Google Search Console data analysis and article rewrites.

**IMPORTANT RULES:**
1. **ONLY rewrite articles that are EXPLICITLY mentioned or requested** - Never rewrite random articles
2. **Remember the current article** - If user asks follow-up questions about "this article" or "the article", continue working on the last article you were discussing
3. **Include technical SEO improvements** - When rewriting, explicitly state improvements to meta description, H tags, schema, page title, etc. and include them in the output
4. **Use full scraped content** - Reference the actual title, meta description, headings, and body text from the scraped page

**For Article Rewrites:**
- Provide the rewritten content in HTML format
- Include improved title tag, meta description, H1, and H2-H6 headings
- Suggest schema markup improvements if applicable
- Explicitly call out what SEO elements were improved
- Maintain the core topic and URL target
- Update outdated information to 2026
- Improve structure and readability

**Available Data:**
- GSC traffic metrics (clicks, impressions, CTR, position)
- Full scraped page content (title, meta, headings, body text)
- Technical SEO elements (schema, canonical, OG tags)

Be specific and reference actual data from the context when available."""
            
            # Build messages with context and conversation history
            # Include last assistant response if we have a current article (for follow-up edits)
            messages = []
            
            # Add conversation history (last 10 messages to keep context manageable)
            recent_history = st.session_state.chat_history[-10:] if len(st.session_state.chat_history) > 10 else st.session_state.chat_history
            
            for msg in recent_history[:-1]:  # Exclude the current user message we just added
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            
            # Build current message with context
            full_message = user_input
            if context:
                full_message = f"{context}\n\n**User Question:** {user_input}"
            
            messages.append({"role": "user", "content": full_message})
            
            response_obj = client.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=4000,
                system=system_message,
                messages=messages
            )
            response = response_obj.content[0].text
        except Exception as e:
            response = f"Error: {str(e)}"
    else:
        response = "Please configure your Claude API key to use chat."
    
    st.session_state.chat_history.append({"role": "assistant", "content": response})
    st.rerun()
