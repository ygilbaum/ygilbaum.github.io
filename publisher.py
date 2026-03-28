import json
import os
import sys
import pickle
import subprocess
import urllib.parse
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- МАГИЧЕСКАЯ СТРОКА ДЛЯ WSL ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 

# --- НАСТРОЙКИ ---
SCOPES = ['https://www.googleapis.com/auth/drive']
CLIENT_SECRET_FILE = '/home/eg/secrets/client_secret.json'
INPUT_FILE = 'input.json'
PARENT_FOLDER_ID = '1_Vjn8i4b0pcaPL4MEPUHs1ywmysOKRCe'
BLOG_ROOT_DIR = "."
TOKEN_PATH = '/tmp/token.pickle'
DOMAIN = "https://norush.cc"

def transliterate(text):
    ru = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    text = text.lower()
    result = []
    for char in text:
        if char in ru:
            result.append(ru[char])
        elif char.isalnum():
            result.append(char)
        elif char.isspace():
            result.append('_')
    return "".join(result)

def authenticate():
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET_FILE):
                print(f"Ошибка: Не найден файл секретов: {CLIENT_SECRET_FILE}")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            flow.redirect_uri = 'http://localhost:8080/'
            auth_url, _ = flow.authorization_url(prompt='consent')
            print(f"Авторизация: {auth_url}")
            code_url = input("Вставь localhost ссылку: ").strip()
            try:
                flow.fetch_token(authorization_response=code_url)
                creds = flow.credentials
            except Exception as e:
                print(f"Ошибка авторизации: {e}")
                sys.exit(1)
        with open(TOKEN_PATH, 'wb') as token:
            pickle.dump(creds, token)
    return creds

def upload_or_update_gdoc(service, title, text_content, lang_prefix):
    full_title = f"[{lang_prefix.upper()}] {title}"
    print(f"Обработка Google Drive: {full_title}...")
    query = f"name = '{full_title}' and '{PARENT_FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name, webViewLink)').execute()
    files = results.get('files', [])
    media = MediaIoBaseUpload(io.BytesIO(text_content.encode('utf-8')), mimetype='text/plain', resumable=False)
    if files:
        file_id = files[0]['id']
        service.files().update(fileId=file_id, media_body=media).execute()
        return file_id
    else:
        file_metadata = {'name': full_title, 'mimeType': 'application/vnd.google-apps.document', 'parents': [PARENT_FOLDER_ID]}
        gdoc = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        return gdoc.get('id')

def git_push_changes(commit_message):
    print("-" * 30)
    print("Публикация (Git)...")
    try:
        os.chdir(BLOG_ROOT_DIR)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
        if not status:
            print("Нет изменений для отправки.")
            return
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"Успех! Отправлено на GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка Git: {e}")

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Ошибка: {INPUT_FILE} не найден.")
        return

    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        title = data.get("title", "Untitled")
        body = data.get("body", "")
        summary = data.get("summary", "") 
        tags = data.get("tags", [])
        lang = data.get("lang", "ru")

        safe_slug = transliterate(title)
        public_url = f"{DOMAIN}/{lang}/posts/{safe_slug}/"

        # --- ФОРМИРОВАНИЕ ССЫЛОК ДЛЯ AI ---
        ai_prompt = (
            f"Я прочитал статью \"{title}\" по ссылке: {public_url}\n\n"
            f"Краткая суть: {summary}\n\n"
            f"Давай обсудим идеи из этого текста. Что ты думаешь об этом?"
        )
        encoded_prompt = urllib.parse.quote(ai_prompt)
        
        # 1. Ссылка для Google AI Studio (Gemini 3 Pro Preview)
        # ВНИМАНИЕ: Если модель еще закрыта в API, ссылка может открыться на дефолтной модели.
        # Но мы просим именно её.
        gemini_link = f"https://aistudio.google.com/prompts/new_chat?model=gemini-3-pro-preview&prompt={encoded_prompt}"
        
        # 2. Ссылка для ChatGPT
        gpt_link = f"https://chatgpt.com/?q={encoded_prompt}"
        claude_link = f"https://claude.ai/new?q={url_encoded_prompt}"
        
        # Markdown футер
        ai_footer = (
            f"\n\n---\n### 🧠 Continue the discussion\n"
            f"Want to discuss this topic further? Choose an AI to debate with:\n\n"
            f"* [Open in **Google AI Studio (Gemini 3 Pro)**]({gemini_link}) _(State of the Art)_\n"
            f"* [Open in **Claude**]({claude_link})\n"
            f"* [Open in **ChatGPT**]({gpt_link})\n"
        )
        if lang == "ru":
            ai_footer = (
                f"\n\n---\n### 🧠 Продолжить диалог\n"
                f"Эта тема требует обсуждения? Выберите AI для дебатов:\n\n"
                f"* [Открыть в **Google AI Studio (Gemini 3 Pro)**]({gemini_link}) _(State of the Art)_\n"
                f"* [Открыть в **Claude**]({claude_link})\n"
                f"* [Открыть в **ChatGPT**]({gpt_link})\n"
            )
        
        blog_body = body + ai_footer
        drive_body = f"{title}\n\nTags: {', '.join(tags)}\nSummary: {summary}\n\n{body}"
        
        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)
        upload_or_update_gdoc(service, title, drive_body, lang)
        
        output_dir = os.path.join(BLOG_ROOT_DIR, "content", lang, "posts")
        os.makedirs(output_dir, exist_ok=True)
        blog_filename = os.path.join(output_dir, safe_slug + ".md")
        
        from datetime import datetime
        date_now = datetime.now().strftime("%Y-%m-%d")

        with open(blog_filename, "w", encoding="utf-8") as f:
            f.write(f"---\n")
            f.write(f"title: \"{title}\"\n")
            f.write(f"date: {date_now}\n")
            f.write(f"draft: false\n")
            f.write(f"tags: {json.dumps(tags, ensure_ascii=False)}\n")
            f.write(f"---\n\n")
            f.write(blog_body)
            
        print(f"Локальный файл: {blog_filename}")
        git_push_changes(f"New post: {title}")

    except Exception as e:
        print(f"Критическая ошибка: {e}")

if __name__ == '__main__':
    main()
