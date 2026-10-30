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

        # 3. Handle Direct File Uploads (PDFs / Images from PWA or Phone)
        elif file:
            file_data = await file.read()
            filename = file.filename.lower()
            pdf_text_snippet = ""

            if filename.endswith('.pdf'):
                default_ext = ".pdf"
                input_type = "PDF"
                try:
                    import pypdf
                    pdf_reader = pypdf.PdfReader(io.BytesIO(file_data))
                    for page in pdf_reader.pages[:3]:
                        pdf_text_snippet += (page.extract_text() or "") + "\n"
                except Exception as pdf_err:
                    print(f"PDF text extraction warning: {pdf_err}")

                full_context = f"Uploaded PDF Filename: {file.filename}\nUser Notes: {raw_text}\nPDF Inner Content Sample:\n{pdf_text_snippet[:2000]}"

            elif filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                default_ext = f".{filename.split('.')[-1]}"
                input_type = "Image"
                full_context = f"Uploaded Image Filename: {file.filename}\nNotes: {raw_text}"
                try:
                    pil_image = Image.open(io.BytesIO(file_data))
                except Exception:
                    pass
            else:
                default_ext = ".bin"
                input_type = "File"
                full_context = f"Uploaded File: {file.filename}\nNotes: {raw_text}"

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

        # 5. Gemini AI Multi-Tier Categorization Prompt
        prompt = f"""
        You are an expert Computer Science and Software Engineering knowledge manager.
        Analyze this full input context (including filenames, user notes, and PDF/image content):
        ---
        {full_context}
        ---

        Categorize strictly into one of these specific technical folders:

        1. SPECIAL FORMAT BUCKETS:
           - Roadmaps: Learning paths, skill trees, career roadmap guides.
           - Cheatsheets: Quick syntax references, command lists, cheat sheets.
           - Projects_Ideas: Open source builds, app ideas, system architecture walkthroughs.
           - Interview_Prep: Interview Q&A sets, behavioral questions, job referral tips, mock tests.

        2. CORE CS & SYSTEM DESIGN SUBJECTS:
           - System_Design: Low-Level Design (LLD), High-Level Design (HLD), SOLID Principles, Design Patterns (Factory, Singleton, Observer, etc.), UML Diagrams, Microservices, System Architecture.
           - DBMS_SQL: SQL queries, Database Indexing, ACID Properties, Transactions, Schema Design, NoSQL.
           - OS: Operating Systems, Deadlocks, Threads, Processes, Paging, Virtual Memory, Concurrency.
           - OOPs: Pure Object-Oriented Concepts, Classes, Inheritance, Polymorphism, Abstraction, Encapsulation.
           - Computer_Networks: TCP/IP, OSI Model, HTTP/HTTPS, WebSockets, DNS, Sockets.
           - AI_LLM: Agentic AI, RAG, Prompt Engineering, LangChain, Gemini, Machine Learning, Neural Networks.
           - WebDev: Frontend, Backend, React, Next.js, FastAPI, Node.js, HTML/CSS, Tailwind.
           - DSA: Algorithms, Data Structures, LeetCode problems, Trees, Graphs, Dynamic Programming.
           - Cloud_DevOps: Docker, Kubernetes, AWS, CI/CD pipelines, Nginx, Server Infra.

        3. FALLBACK RULES:
           - If Filename or Content mentions LLD, Low Level Design, SOLID, Design Patterns, or HLD -> Category MUST be 'System_Design'.
           - Extract a concise topic slug from the filename or text (e.g., 'lld_notes' for 'LLD notes.pdf').
           - ONLY use 'General' if the content is completely non-technical or unclassifiable.

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
            result = {"category": "System_Design", "topic_slug": "lld_notes"}

        category = result.get("category", "General")
        raw_slug = result.get("topic_slug", "saved_resource").strip().lower()
        clean_slug = re.sub(r'[^a-z0-9_]', '', raw_slug.replace(' ', '_')) or "saved_resource"

        today_date = datetime.now().strftime("%Y-%m-%d")
        github_path = f"{category}/{today_date}_{clean_slug}{default_ext}"

        # 6. Commit or Update File in GitHub Repo
        repo = get_github_repo()
        
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