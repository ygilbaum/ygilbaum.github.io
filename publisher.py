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
from datetime import datetime

# --- МАГИЧЕСКАЯ СТРОКА ДЛЯ WSL ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# --- НАСТРОЙКИ ---
SCOPES = ['https://www.googleapis.com/auth/drive']
CLIENT_SECRET_FILE = '/home/eg/secrets/client_secret.json'
INPUT_FILE = 'input.json'
MANIFEST_FILE = 'content_manifest.json'
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

def load_manifest():
    if os.path.exists(MANIFEST_FILE):
        try:
            with open(MANIFEST_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Предупреждение: Ошибка чтения манифеста ({e}). Создаем новый.")
    return {}

def save_manifest(manifest):
    with open(MANIFEST_FILE, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def upload_or_update_gdoc(service, title, text_content, lang_prefix):
    full_title = f"[{lang_prefix.upper()}] {title}"
    print(f"Обработка Google Drive: {full_title}...")
    query = f"name = '{full_title}' and '{PARENT_FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    media = MediaIoBaseUpload(io.BytesIO(text_content.encode('utf-8')), mimetype='text/plain', resumable=False)
    if files:
        file_id = files[0]['id']
        service.files().update(fileId=file_id, media_body=media).execute()
        return file_id
    else:
        file_metadata = {'name': full_title, 'mimeType': 'application/vnd.google-apps.document', 'parents': [PARENT_FOLDER_ID]}
        gdoc = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
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
        print(f"Успех! Изменения отправлены в репозиторий.")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка Git: {e}")

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Ошибка: {INPUT_FILE} не найден.")
        return

    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            content = json.load(f)
            items = content if isinstance(content, list) else [content]

        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)
        manifest = load_manifest()

        date_iso = datetime.now().strftime("%Y-%m-%d")
        last_updated_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        processed_titles = []

        for data in items:
            title = data.get("title", "Untitled")
            body = data.get("body", "")
            summary = data.get("summary", "")
            tags = data.get("tags", [])
            lang = data.get("lang", "ru")
            post_id = str(data.get("id"))
            metadata = data.get("metadata", {})

            if not post_id:
                print(f"Ошибка: Пропуск '{title}', не указан ID.")
                continue

            # Логика версионности
            if post_id in manifest:
                version = manifest[post_id].get("current_version", 1) + 1
                original_date = manifest[post_id].get("date", date_iso)
            else:
                version = 1
                original_date = date_iso

            # Обновляем манифест
            manifest[post_id] = {
                "filename": f"{post_id}.md",
                "lang": lang,
                "current_version": version,
                "date": original_date,
                "last_updated": last_updated_ts,
                "title": title,
                "metadata": metadata
            }

            # Формирование URL и футера
            public_url = f"{DOMAIN}/{lang}/posts/{post_id}/"

            if lang == "ru":
                ai_prompt = f"Я прочитал статью \"{title}\" по ссылке: {public_url}\n\nКраткая суть: {summary}\n\nДавай обсудим идеи из этого текста."
                footer_title = "### 🧠 Продолжить диалог"
                footer_text = "Эта тема требует обсуждения? Выберите AI для дебатов:"
            elif lang == "he":
                ai_prompt = f"קראתי את המאמר \"{title}\" בקישור הבא: {public_url}\n\nתקציר: {summary}\n\nבוא נדון ברעיונות המוצגים בטקסט זה."
                footer_title = "### 🧠 המשך הדיון"
                footer_text = "האם הנושא דורש דיון? בחר בינה מלאכותית לעימות:"
            else:
                ai_prompt = f"I read the article \"{title}\" at the following link: {public_url}\n\nSummary: {summary}\n\nLet's discuss the ideas."
                footer_title = "### 🧠 Continue the discussion"
                footer_text = "Want to discuss this topic further?"

            encoded_prompt = urllib.parse.quote(ai_prompt)
            ai_footer = (
                f"\n\n---\n{footer_title}\n"
                f"{footer_text}\n\n"
                f"* [Gemini 3 Pro](https://aistudio.google.com/prompts/new_chat?model=gemini-3-pro-preview&prompt={encoded_prompt})\n"
                f"* [Claude](https://claude.ai/new?q={encoded_prompt})\n"
                f"* [ChatGPT](https://chatgpt.com/?q={encoded_prompt})\n"
            )

            # Блок метаданных в боди
            version_footer = (
                f"\n\n---\n"
                f"**Meta-information:**\n"
                f"* **ID:** `{post_id}`\n"
                f"* **Version:** `{version}`\n"
                f"* **Last Updated:** `{last_updated_ts}`\n"
            )

            blog_body = body + ai_footer + version_footer
            drive_body = f"ID: {post_id} | v{version}\n{title}\n\nTags: {', '.join(tags)}\n\n{body}"

            upload_or_update_gdoc(service, title, drive_body, lang)

            # Запись MD файла
            output_dir = os.path.join(BLOG_ROOT_DIR, "content", lang, "posts")
            os.makedirs(output_dir, exist_ok=True)
            blog_filename = os.path.join(output_dir, f"{post_id}.md")

            with open(blog_filename, "w", encoding="utf-8") as f:
                f.write("---\n")
                f.write(f"title: \"{title}\"\n")
                f.write(f"id: \"{post_id}\"\n")
                f.write(f"version: {version}\n")
                f.write(f"date: {original_date}\n")
                f.write(f"lastmod: \"{last_updated_ts}\"\n")
                f.write(f"tags: {json.dumps(tags, ensure_ascii=False)}\n")
                if metadata:
                    f.write(f"metadata: {json.dumps(metadata, ensure_ascii=False)}\n")
                f.write("---\n\n")
                f.write(blog_body)

            processed_titles.append(f"{title} (v{version})")
            print(f"Готово ({lang}): {blog_filename}")

        save_manifest(manifest)

        if processed_titles:
            git_push_changes(f"Update: {', '.join(processed_titles)}")

    except Exception as e:
        print(f"Критическая ошибка: {e}")

if __name__ == '__main__':
    main()

