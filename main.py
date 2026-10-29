import json
import os
import re
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from github import Github
from google import genai

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_github_repo():
    g = Github(GITHUB_TOKEN)
    return g.get_repo(REPO_NAME)

def extract_link_details(url: str):
    try:
        api_url = f"https://api.microlink.io?url={url}"
        res = requests.get(api_url, timeout=4)
        if res.status_code == 200:
            data = res.json().get("data", {})
            title = data.get("title") or ""
            description = data.get("description") or ""
            
            # Junk & Auth Wall Filter (Filters out Chinese/Japanese language selectors & generic headers)
            junk_keywords = ["linkedin", "log in", "sign up", "選擇語言", "select language", "join linkedin"]
            
            if any(junk in title.lower() for junk in junk_keywords):
                title = ""
            if any(junk in description.lower() for junk in junk_keywords):
                description = ""
                
            return title, description
    except Exception as e:
        print(f"Extraction failed for {url}: {e}")
    
    return "", ""

@app.post("/upload")
async def handle_pwa_upload(
    text: str = Form(None),
    file: UploadFile = File(None)
):
    try:
        raw_text = (text or "").strip()
        urls = re.findall(r'(https?://[^\s]+)', raw_text)
        
        extracted_title = ""
        extracted_desc = ""
        
        # 1. Handle Web Links & LinkedIn Posts
        if urls:
            target_url = urls[0]
            extracted_title, extracted_desc = extract_link_details(target_url)
            
            # Remove raw URL from notes to get purely user typed text
            clean_user_notes = raw_text.replace(target_url, "").strip()
            
            # Context constructed for AI categorization
            full_context = f"User Notes: {clean_user_notes}\nTitle: {extracted_title}\nSnippet: {extracted_desc}".strip()
            
            # Formatting clean Markdown output
            file_content = f"# {clean_user_notes[:40] or extracted_title or 'LinkedIn Resource'}\n\n"
            file_content += f"**Source URL:** {target_url}\n\n---\n\n"
            
            if extracted_desc:
                file_content += f"**Extracted Summary:**\n{extracted_desc}\n\n"
                
            file_content += f"**User Notes & Context:**\n{clean_user_notes if clean_user_notes else 'No additional notes provided.'}"
            
            file_data = file_content.encode('utf-8')
            default_ext = ".md"
            input_type = "Link Archive"

        # 2. Handle File Uploads (Images / PDFs)
        elif file:
            file_data = await file.read()
            filename = file.filename.lower()
            full_context = f"File Upload: {file.filename} Notes: {raw_text}"
            if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                default_ext = ".png"
                input_type = "Image"
            elif filename.endswith('.pdf'):
                default_ext = ".pdf"
                input_type = "PDF"
            else:
                default_ext = ".bin"
                input_type = "File"

        # 3. Handle Plain Text Notes
        elif raw_text:
            full_context = raw_text
            file_data = f"# Note Archive\n\n{raw_text}".encode('utf-8')
            default_ext = ".md"
            input_type = "Text Note"
        else:
            raise HTTPException(status_code=400, detail="No content provided.")

        # 4. Gemini AI Strict Categorization Prompt
        prompt = f"""
        You are an expert AI categorizer for a developer's Knowledge Vault.
        Analyze this full input context:
        ---
        {full_context}
        ---

        Categorize strictly based on technical topic:
        - If context mentions Agentic AI, Agents, LLM, RAG, Prompt Engineering, LangChain, OpenAI, Gemini, GenAI -> Category MUST be 'AI_LLM'
        - If context mentions React, Next.js, FastAPI, Node.js, HTML, CSS, Frontend, Backend -> Category MUST be 'WebDev'
        - If context mentions Microservices, Distributed Systems, Kafka, System Architecture -> Category MUST be 'System_Design'
        - If context mentions LeetCode, DSA, Trees, Graphs, Algorithms -> Category MUST be 'DSA'
        - If context is strictly about job applications, resumes, referrals -> Category MUST be 'Career_Resources'
        - Otherwise -> Category 'General'

        Return ONLY a JSON object:
        {{
            "category": "Folder_Name",
            "filename": "YYYY-MM-DD_short_descriptive_name"
        }}
        """

        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt
        )
        
        cleaned_json = response.text.replace('```json', '').replace('```', '').strip()
        result = json.loads(cleaned_json)

        category = result.get("category", "General")
        base_name = result.get("filename", "saved_resource")
        github_path = f"{category}/{base_name}{default_ext}"

        # 5. Commit to GitHub Repo
        repo = get_github_repo()
        repo.create_file(
            path=github_path,
            message=f"PWA archive ({input_type}): {base_name}",
            content=file_data
        )

        return {"status": "success", "path": github_path, "category": category}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))