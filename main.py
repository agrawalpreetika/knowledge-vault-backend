import io
import json
import os
import re
import requests
import time
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

def sanitize_slug(name: str) -> str:
    """Helper to convert raw file name or title into clean snake_case slug"""
    clean = re.sub(r'\.[^/.]+$', '', name)  # Remove extension if present
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', clean.replace(' ', '_')).lower()
    clean = re.sub(r'_+', '_', clean).strip('_')
    return clean or "resource_file"

def derive_keyword_category(context_str: str) -> str:
    """Fallback classifier based on keywords if Gemini fails"""
    ctx = context_str.lower()
    if any(k in ctx for k in ["sql", "database", "dbms", "postgres", "mysql", "queries"]):
        return "DBMS_SQL"
    elif any(k in ctx for k in ["roadmap", "pathway", "guide", "career"]):
        return "Roadmaps"
    elif any(k in ctx for k in ["cheatsheet", "cheat sheet", "syntax", "quick reference"]):
        return "Cheatsheets"
    elif any(k in ctx for k in ["os", "operating system", "deadlock", "process", "thread", "paging"]):
        return "OS"
    elif any(k in ctx for k in ["lld", "hld", "system design", "solid", "design pattern", "uml"]):
        return "System_Design"
    elif any(k in ctx for k in ["oop", "oops", "polymorphism", "inheritance", "abstraction"]):
        return "OOPs"
    elif any(k in ctx for k in ["llm", "rag", "agent", "gemini", "gpt", "prompt", "ai"]):
        return "AI_LLM"
    elif any(k in ctx for k in ["react", "nextjs", "fastapi", "node", "web", "frontend", "backend"]):
        return "WebDev"
    elif any(k in ctx for k in ["dsa", "leetcode", "algorithm", "binary tree", "graph"]):
        return "DSA"
    return "General"

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
        fallback_slug = "resource_file"
        
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
            fallback_slug = sanitize_slug(extracted_title or clean_user_notes[:30] or "link_archive")

        # 3. Handle Direct File Uploads (PDFs / Images)
        elif file:
            file_data = await file.read()
            filename = file.filename.lower()
            fallback_slug = sanitize_slug(file.filename)
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

                full_context = f"Uploaded Original Filename: {file.filename}\nUser Notes: {raw_text}\nPDF Snippet:\n{pdf_text_snippet[:2000]}"

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
                full_context = f"Uploaded Original Filename: {file.filename}\nNotes: {raw_text}"

        # 4. Handle Plain Text Notes
        elif raw_text:
            full_context = raw_text
            file_content = f"# Note Archive\n\n{raw_text}"
            if image_url:
                file_content += f"\n\n**Image Resource:** ![Image]({image_url})"
            file_data = file_content.encode('utf-8')
            default_ext = ".md"
            input_type = "Text Note"
            fallback_slug = sanitize_slug(raw_text[:30])
        else:
            raise HTTPException(status_code=400, detail="No content provided.")

        # 5. Gemini AI Multi-Tier Categorization Prompt
        prompt = f"""
        You are an expert Computer Science and Software Engineering knowledge manager.
        Analyze this full input context (original filename, notes, and inner text):
        ---
        {full_context}
        ---

        1. CATEGORY SELECTION RULES:
           - DBMS_SQL: SQL queries, SQL handbooks, Database Indexing, ACID, Transactions, Schema Design, MySQL, Postgres, NoSQL.
           - Roadmaps: Explicit learning paths, skill trees, roadmaps, career preparation plans.
           - Cheatsheets: Quick syntax reference sheets, command lists, cheat sheets.
           - System_Design: Low-Level Design (LLD), High-Level Design (HLD), SOLID Principles, Design Patterns, UML Diagrams, Microservices, Architecture.
           - OS: Operating Systems, Process Synchronization, Deadlocks, Threads, Processes, Paging, Memory.
           - OOPs: Object Oriented Programming, Classes, Inheritance, Polymorphism, Abstraction, Encapsulation.
           - AI_LLM: LLM, Agentic AI, RAG, Prompt Engineering, LangChain, Machine Learning, Neural Networks.
           - WebDev: Frontend, Backend, React, Next.js, FastAPI, Node.js, Tailwind, HTML/CSS.
           - DSA: Algorithms, Data Structures, LeetCode, Arrays, Trees, Graphs, Dynamic Programming.
           - Cloud_DevOps: Docker, Kubernetes, AWS, CI/CD pipelines, Nginx, Linux administration.

        2. TOPIC SLUG RULES:
           - Base the topic_slug on BOTH the original filename AND the core technical subject.
           - Example 1: Original filename 'SQL Handbook.pdf' -> topic_slug: 'sql_handbook'
           - Example 2: Original filename 'NLD 11th Roadmap.pdf' -> category: 'Roadmaps', topic_slug: 'nld_11th_roadmap'
           - Example 3: Original filename 'NLD Notes.pdf' -> category: 'System_Design', topic_slug: 'nld_notes'
           - NEVER use 'lld_notes' or 'system_design' as a default unless the content is genuinely about LLD / Design Patterns.

        Return ONLY JSON format:
        {{
            "category": "FolderName",
            "topic_slug": "short_snake_case_descriptive_name"
        }}
        """

        gemini_contents = []
        if pil_image:
            gemini_contents.append(pil_image)
        gemini_contents.append(prompt)

        # Keyword-based fallback category in case API call fails
        fallback_category = derive_keyword_category(full_context)

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
            result = {"category": fallback_category, "topic_slug": fallback_slug}

        category = result.get("category", fallback_category)
        raw_slug = result.get("topic_slug", fallback_slug).strip().lower()
        clean_slug = sanitize_slug(raw_slug)

        today_date = datetime.now().strftime("%Y-%m-%d")
        base_github_path = f"{category}/{today_date}_{clean_slug}"
        github_path = f"{base_github_path}{default_ext}"

        # 6. Commit to GitHub Repo with Duplicate Overwrite Protection
        repo = get_github_repo()
        
        try:
            repo.get_contents(github_path)
            # File already exists on GitHub! Add timestamp hash suffix so no file is EVER overwritten.
            timestamp_suffix = int(time.time()) % 10000
            github_path = f"{base_github_path}_{timestamp_suffix}{default_ext}"
        except Exception:
            # File does not exist yet, clean path is safe to use
            pass

        repo.create_file(
            path=github_path,
            message=f"PWA archive ({input_type}): {clean_slug}",
            content=file_data
        )

        return {"status": "success", "path": github_path, "category": category}

    except Exception as e:
        print(f"Error handling upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))