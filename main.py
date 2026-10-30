import io
import json
import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from github import Github
from google import genai
from google.genai import types
from PIL import Image

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
    image_url: str = Form(None),
    file: UploadFile = File(None)
):
    try:
        raw_text = (text or "").strip()
        urls = re.findall(r'(https?://[^\s]+)', raw_text)
        
        extracted_title = ""
        extracted_desc = ""
        pil_image = None
        
        # 1. Image URL download for Gemini Vision
        if image_url:
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
                img_res = requests.get(image_url, headers=headers, timeout=10)
                if img_res.status_code == 200:
                    pil_image = Image.open(io.BytesIO(img_res.content))
            except Exception as e:
                print(f"Failed to load image from URL for Gemini Vision: {e}")

        # 2. Handle Web Links & LinkedIn Posts
        if urls:
            target_url = urls[0]
            extracted_title, extracted_desc = extract_link_details(target_url)
            
            clean_user_notes = raw_text.replace(target_url, "").strip()
            
            full_context = f"User Notes: {clean_user_notes}\nTitle: {extracted_title}\nSnippet: {extracted_desc}".strip()
            
            file_content = f"# {clean_user_notes[:40] or extracted_title or 'LinkedIn Resource'}\n\n"
            file_content += f"**Source URL:** {target_url}\n\n---\n\n"
            
            if image_url:
                file_content += f"**Archived Image:** ![LinkedIn Image]({image_url})\n\n"
                
            if extracted_desc:
                file_content += f"**Extracted Summary:**\n{extracted_desc}\n\n"
                
            file_content += f"**User Notes & Context:**\n{clean_user_notes if clean_user_notes else 'No additional notes provided.'}"
            
            file_data = file_content.encode('utf-8')
            default_ext = ".md"
            input_type = "Link Archive"

        # 3. Handle Direct File Uploads (Images / PDFs from PWA)
        elif file:
            file_data = await file.read()
            filename = file.filename.lower()
            full_context = f"File Upload: {file.filename} Notes: {raw_text}"
            if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                default_ext = f".{filename.split('.')[-1]}"
                input_type = "Image"
                try:
                    pil_image = Image.open(io.BytesIO(file_data))
                except Exception:
                    pass
            elif filename.endswith('.pdf'):
                default_ext = ".pdf"
                input_type = "PDF"
            else:
                default_ext = ".bin"
                input_type = "File"

        # 4. Handle Plain Text Notes
        elif raw_text:
            full_context = raw_text
            file_content = f"# Note Archive\n\n{raw_text}"
            if image_url:
                file_content += f"\n\n**Image Resource:** ![Image]({image_url})"
            file_data = file_content.encode('utf-8')
            default_ext = ".md"
            input_type = "Text Note"
        else:
            raise HTTPException(status_code=400, detail="No content provided.")

        # 5. Gemini AI Dynamic Multi-Tier Categorization
        prompt = f"""
        You are an expert Computer Science and Software Engineering knowledge manager.
        Analyze this full input context and any accompanying visual image content:
        ---
        {full_context}
        ---

        Categorize the entry into the most specific and accurate technical folder:

        1. PRIMARY TECH BUCKETS (Prefer these if strongly relevant):
           - AI_LLM: Agentic AI, LLMs, RAG, LangChain, Machine Learning, Neural Networks, PyTorch.
           - WebDev: React, Next.js, FastAPI, Node.js, Frontend, Backend, Web APIs, CSS/Tailwind.
           - System_Design: Microservices, Distributed Systems, Kafka, System Architecture, Caching.
           - DSA: Algorithms, Data Structures, LeetCode, Arrays, Trees, Graphs, Dynamic Programming.
           - Career_Resources: Job postings, Resume tips, Interview experiences, Referrals.

        2. DYNAMIC CS & TECH DOMAINS (If the content covers a distinct CS subject or domain NOT in the primary buckets, create a concise PascalCase folder name):
           - Operating Systems / Deadlocks / Threads / Memory Management -> 'OS'
           - Object-Oriented Programming / Design Patterns / SOLID principles -> 'OOPs'
           - Database Systems / SQL / Indexing / ACID properties -> 'DBMS'
           - Computer Networks / TCP/IP / HTTP / DNS / Sockets -> 'Computer_Networks'
           - Mobile App Development / Flutter / React Native / Android -> 'Mobile_Dev'
           - DevOps / Docker / Kubernetes / CI-CD / Cloud Infrastructure -> 'Cloud_DevOps'
           - Cybersecurity / Cryptography / Penetration Testing -> 'CyberSecurity'
           - Low-Level Programming / C / C++ Memory -> 'Cpp_Systems'

        3. FALLBACK RULE:
           - If the topic is a distinct technical subject not listed above, create a clean, short PascalCase category name (e.g., 'Compiler_Design', 'BlockChain').
           - ONLY use 'General' if the content is completely non-technical, personal, or unclassifiable.

        Return ONLY JSON format:
        {{
            "category": "FolderName",
            "topic_slug": "short_snake_case_descriptive_name_without_date"
        }}
        """

        gemini_contents = []
        if pil_image:
            gemini_contents.append(pil_image)
        gemini_contents.append(prompt)

        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=gemini_contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            result = json.loads(response.text)
        except Exception as ai_err:
            print(f"Gemini processing fallback triggered: {ai_err}")
            result = {"category": "General", "topic_slug": "saved_resource"}

        category = result.get("category", "General")
        raw_slug = result.get("topic_slug", "saved_resource").strip().lower()
        clean_slug = re.sub(r'[^a-z0-9_]', '', raw_slug.replace(' ', '_')) or "saved_resource"

        # Today's System Date Enforcement
        today_date = datetime.now().strftime("%Y-%m-%d")
        github_path = f"{category}/{today_date}_{clean_slug}{default_ext}"

        # 6. Commit to GitHub Repo
        repo = get_github_repo()
        
        # Check if file already exists to avoid overwrite error
        try:
            existing_file = repo.get_contents(github_path)
            repo.update_file(
                path=github_path,
                message=f"Update archive ({input_type}): {clean_slug}",
                content=file_data,
                sha=existing_file.sha
            )
        except Exception:
            repo.create_file(
                path=github_path,
                message=f"PWA archive ({input_type}): {clean_slug}",
                content=file_data
            )

        return {"status": "success", "path": github_path, "category": category}

    except Exception as e:
        print(f"Error handling upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))