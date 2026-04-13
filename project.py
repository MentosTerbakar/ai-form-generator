import streamlit as st
import re
import os
import json
import pandas as pd
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google import genai
#AIzaSyC4K3mSuPxhH9elpNEqs3ZN9SSMr1yYxJc

# --- CONFIGURATION ---
# This scope tells Google exactly what we want permission to do: Read the form structure.
SCOPES = ['https://www.googleapis.com/auth/forms.body.readonly']

# --- 1. GOOGLE API LOGIC ---
def authenticate_google():
    """Handles the Google Login popup and saves the session token."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('forms', 'v1', credentials=creds)

def fetch_google_form(form_id):
    """Uses the authenticated service to fetch the raw JSON form data."""
    service = authenticate_google()
    return service.forms().get(formId=form_id).execute()

def extract_form_id(url):
    """Finds the unique ID hidden inside the Google Form link."""
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else None

# --- 2. TRANSLATOR LOGIC ---
def translate_form_to_text(raw_data):
    """Converts raw Google Forms JSON into a plain English prompt, including grids."""
    title = raw_data.get('info', {}).get('title', 'Untitled Form')
    description = raw_data.get('info', {}).get('description', 'No description provided.')
    
    context = f"Survey Title: {title}\nContext: {description}\n\nSurvey Questions:\n"
    items = raw_data.get('items', [])
    question_num = 1
    
    for item in items:
        # --- HANDLE STANDARD QUESTIONS ---
        if 'questionItem' in item:
            q_title = item.get('title', 'Untitled Question')
            q_data = item['questionItem']['question']
            
            if 'textQuestion' in q_data:
                context += f"{question_num}. '{q_title}' (Format: User must type a realistic text answer)\n"
            elif 'dateQuestion' in q_data:
                context += f"{question_num}. '{q_title}' (Format: Date YYYY-MM-DD)\n"
            elif 'choiceQuestion' in q_data:
                options = [opt.get('value', 'Blank') for opt in q_data['choiceQuestion'].get('options', [])]
                context += f"{question_num}. '{q_title}' (Format: Pick exactly one from: {', '.join(options)})\n"
            elif 'scaleQuestion' in q_data:
                low = q_data['scaleQuestion'].get('low', 1)
                high = q_data['scaleQuestion'].get('high', 5)
                context += f"{question_num}. '{q_title}' (Format: Integer from {low} to {high})\n"
            else:
                context += f"{question_num}. '{q_title}' (Format: Standard answer)\n"
            question_num += 1

        # --- HANDLE GRID/MATRIX QUESTIONS ---
        elif 'questionGroupItem' in item:
            group_data = item['questionGroupItem']
            if 'grid' in group_data and 'columns' in group_data['grid']:
                options = [opt.get('value', '') for opt in group_data['grid']['columns'].get('options', [])]
                options_str = ", ".join(options)
                context += f"Grid Section Options (Must pick one per row): {options_str}\n"
            
            for row in group_data.get('questions', []):
                if 'rowQuestion' in row:
                    row_title = row['rowQuestion'].get('title', 'Untitled Row')
                    context += f"{question_num}. '{row_title}' (Format: Pick from grid options)\n"
                    question_num += 1
            context += "\n"
    return context

# --- 3. AI GENERATION LOGIC ---
def generate_synthetic_data(context, num_responses, api_key):
    """Sends the context to Gemini 2.5 using the new SDK and asks for JSON back."""
    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    You are an expert synthetic data generator. 
    Read the survey context below and generate EXACTLY {num_responses} realistic respondent profiles.
    
    CRITICAL RULES:
    1. You MUST output ONLY a valid JSON array of objects. No introductory text.
    2. Do NOT wrap the JSON in markdown (do not use ```json). Just start with [ and end with ].
    3. The keys for each JSON object must be the exact question titles inside the single quotes.
    4. The values must follow the format rules requested. Ensure diversity in the answers!

    SURVEY CONTEXT:
    {context}
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    
    return response.text

# --- 4. STREAMLIT UI ---
st.set_page_config(page_title="AI Survey Generator", page_icon="🤖")

st.sidebar.markdown("### ⚙️ Settings")
gemini_api_key = st.sidebar.text_input("Enter Gemini API Key:", type="password")
st.sidebar.markdown("*Get a free key at [Google AI Studio](https://aistudio.google.com/)*")

st.title("🤖 AI Synthetic Survey Generator")
st.write("Generate highly realistic, context-aware CSV data from any Google Form.")

st.markdown("### Step 1: Form Details")
form_url = st.text_input("Paste your Google Form Edit URL here:")
num_responses = st.number_input("How many synthetic responses do you need?", min_value=1, max_value=500, value=5)

if st.button("Generate Synthetic Data", type="primary"):
    if not gemini_api_key or len(gemini_api_key) < 30:
        st.error("🚨 Please enter a valid Gemini API Key in the sidebar first!")
    elif not form_url:
        st.warning("⚠️ Please paste a Google Form URL.")
    else:
        form_id = extract_form_id(form_url)
        
        if form_id:
            try:
                # Phase 1: Fetch and Translate
                with st.spinner("1/3: Fetching form structure from Google..."):
                    raw_form_data = fetch_google_form(form_id)
                    translated_context = translate_form_to_text(raw_form_data)
                
                # Phase 2: AI Generation
                with st.spinner(f"2/3: AI is forging {num_responses} realistic responses using Gemini 2.5 Flash..."):
                    ai_json_output = generate_synthetic_data(translated_context, num_responses, gemini_api_key)
                
                # Phase 3: Format and Export
                with st.spinner("3/3: Formatting data into CSV..."):
                    data_objects = json.loads(ai_json_output)
                    df = pd.DataFrame(data_objects)
                    csv_data = df.to_csv(index=False).encode('utf-8')
                
                # Success & Download Button
                st.success("🎉 Synthetic Data Successfully Generated!")
                st.dataframe(df)
                
                st.download_button(
                    label="💾 Download CSV",
                    data=csv_data,
                    file_name="synthetic_form_data.csv",
                    mime="text/csv",
                )
                    
            except json.JSONDecodeError:
                st.error("The AI did not return a perfectly formatted JSON. Please click Generate again.")
                with st.expander("View Raw AI Output"):
                    st.text(ai_json_output)
            except Exception as e:
                st.error(f"An error occurred: {e}")
        else:
            st.error("Could not find a valid Form ID. Make sure it looks like: [https://docs.google.com/forms/d/YOUR_ID_HERE/edit](https://docs.google.com/forms/d/YOUR_ID_HERE/edit)")