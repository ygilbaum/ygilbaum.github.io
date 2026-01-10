import json
import os
import sys
import pickle
import subprocess
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- МАГИЧЕСКАЯ СТРОКА ДЛЯ WSL ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 

# --- НАСТРОЙКИ ---
SCOPES = ['https://www.googleapis.com/auth/drive']
CLIENT_SECRET_FILE = '/home/ygilbaum/secret/client_secret.json'
INPUT_FILE = 'input.json'
PARENT_FOLDER_ID = '1_Vjn8i4b0pcaPL4MEPUHs1ywmysOKRCe'  # <--- НЕ ЗАБУДЬ ВЕРНУТЬ СВОЙ ID

# Путь к папке блога (где лежит hugo.yaml). 
# Если скрипт лежит ВНУТРИ папки блога, оставь "."
# Если скрипт снаружи, укажи полный путь, например "/home/ygilbaum/blog_source"
BLOG_ROOT_DIR = "." 

def authenticate():
    creds = None
    if os.path.exists('/tmp/token.pickle'):
        with open('/tmp/token.pickle', 'rb') as token:
            creds = pickle.load(token)
            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET_FILE):
                print(f"Ошибка: Не найден файл {CLIENT_SECRET_FILE}.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, SCOPES)
            flow.redirect_uri = 'http://localhost:8080/'
            auth_url, _ = flow.authorization_url(prompt='consent')
            print(f"Авторизация: {auth_url}")
            code_url = input("Вставь ссылку localhost сюда: ").strip()
            try:
                flow.fetch_token(authorization_response=code_url)
                creds = flow.credentials
            except Exception as e:
                print(f"Ошибка: {e}")
                sys.exit(1)
        with open('/tmp/token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

def upload_as_gdoc(service, title, text_content):
    print(f"Загружаю в Google Drive: {title}...")
    file_metadata = {'name': title, 'mimeType': 'application/vnd.google-apps.document', 'parents': [PARENT_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(text_content.encode('utf-8')), mimetype='text/plain', resumable=False)
    try:
        gdoc = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        print(f"Google Doc готов: {gdoc.get('webViewLink')}")
    except Exception as e:
        print(f"Ошибка GDrive: {e}")

def git_push_changes(commit_message):
    print("-" * 30)
    print("Начинаю публикацию в блог (Git)...")
    try:
        # Переходим в папку блога для выполнения команд
        os.chdir(BLOG_ROOT_DIR)
        
        # 1. Add
        subprocess.run(["git", "add", "."], check=True)
        
        # 2. Commit
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        
        # 3. Push
        # Мы используем subprocess, чтобы вывод git'а был виден в терминале
        subprocess.run(["git", "push"], check=True)
        
        print(f"Успех! Статья отправлена на norush.cc")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при работе с Git: {e}")
    except FileNotFoundError:
        print("Ошибка: Не установлен Git или неверный путь к папке блога.")

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Ошибка: Файл {INPUT_FILE} не найден.")
        return

    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        title = data.get("title", "Untitled")
        body = data.get("body", "")
        tags = data.get("tags", [])
        lang = data.get("lang", "ru")
        
        full_text = f"{title}\n\nTags: {', '.join(tags)}\n\n{body}"
        
        # 1. Google Drive
        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)
        upload_as_gdoc(service, f"[{lang.upper()}] {title}", full_text)
        
        # 2. Локальный файл блога
        # Путь теперь строится от BLOG_ROOT_DIR
        output_dir = os.path.join(BLOG_ROOT_DIR, "content", lang, "posts")
        os.makedirs(output_dir, exist_ok=True)
        
        safe_title = title.replace(" ", "_").replace(":", "").replace("/", "-").lower()
        blog_filename = os.path.join(output_dir, f"{safe_title}.md")
        
        from datetime import datetime
        date_now = datetime.now().strftime("%Y-%m-%d")

        with open(blog_filename, "w", encoding="utf-8") as f:
            f.write(f"---\n")
            f.write(f"title: \"{title}\"\n")
            f.write(f"date: {date_now}\n")
            f.write(f"tags: {json.dumps(tags, ensure_ascii=False)}\n") # Корректный формат списка yaml
            f.write(f"---\n\n")
            f.write(body)
            
        print(f"Файл создан: {blog_filename}")
        
        # 3. Публикация (Git Push)
        git_push_changes(f"New post: {title}")

    except Exception as e:
        print(f"Критическая ошибка: {e}")

if __name__ == '__main__':
    main()

