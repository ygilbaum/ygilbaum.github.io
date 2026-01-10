import json
import os
import sys
import pickle
import subprocess
import re
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- МАГИЧЕСКАЯ СТРОКА ДЛЯ WSL ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 

# --- НАСТРОЙКИ (Твои боевые параметры) ---
SCOPES = ['https://www.googleapis.com/auth/drive']
CLIENT_SECRET_FILE = '/home/ygilbaum/secret/client_secret.json'
INPUT_FILE = 'input.json'
PARENT_FOLDER_ID = '1_Vjn8i4b0pcaPL4MEPUHs1ywmysOKRCe'
BLOG_ROOT_DIR = "." 

def transliterate(text):
    """Превращает 'Начало пути' в 'nachalo_puti' для URL"""
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
        # Все остальные символы игнорируем
            
    return "".join(result)

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
                print(f"Ошибка: Не найден файл секретов по пути: {CLIENT_SECRET_FILE}")
                sys.exit(1)
                
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            flow.redirect_uri = 'http://localhost:8080/'
            auth_url, _ = flow.authorization_url(prompt='consent')
            print(f"Авторизация нужна (токен истек или отсутствует).\nСсылка: {auth_url}")
            code_url = input("Вставь localhost ссылку: ").strip()
            try:
                flow.fetch_token(authorization_response=code_url)
                creds = flow.credentials
            except Exception as e:
                print(f"Ошибка авторизации: {e}")
                sys.exit(1)
                
        with open('/tmp/token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

def upload_or_update_gdoc(service, title, text_content, lang_prefix):
    """
    Ищет файл с таким именем.
    Если есть -> обновляет (создает версию).
    Если нет -> создает новый.
    """
    full_title = f"[{lang_prefix.upper()}] {title}"
    print(f"Обработка Google Drive: {full_title}...")
    
    # 1. Поиск существующего файла
    query = f"name = '{full_title}' and '{PARENT_FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name, webViewLink)').execute()
    files = results.get('files', [])

    media = MediaIoBaseUpload(io.BytesIO(text_content.encode('utf-8')), mimetype='text/plain', resumable=False)

    if files:
        # ОБНОВЛЕНИЕ (Update)
        file_id = files[0]['id']
        link = files[0]['webViewLink']
        print(f"  -> Нашел существующий файл (ID: {file_id}). Обновляю версию...")
        try:
            service.files().update(fileId=file_id, media_body=media).execute()
            print(f"  -> Успешно обновлено. Ссылка та же: {link}")
            return file_id
        except Exception as e:
            print(f"Ошибка при обновлении: {e}")
            return None
    else:
        # СОЗДАНИЕ (Create)
        print(f"  -> Файл не найден. Создаю новый...")
        file_metadata = {'name': full_title, 'mimeType': 'application/vnd.google-apps.document', 'parents': [PARENT_FOLDER_ID]}
        try:
            gdoc = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
            print(f"  -> Создан! Ссылка: {gdoc.get('webViewLink')}")
            return gdoc.get('id')
        except Exception as e:
            print(f"Ошибка при создании: {e}")
            return None

def git_push_changes(commit_message):
    print("-" * 30)
    print("Публикация (Git)...")
    try:
        os.chdir(BLOG_ROOT_DIR)
        
        # Проверяем статус, есть ли что коммитить
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
        if not status:
            print("Нет изменений для отправки в Git.")
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
        tags = data.get("tags", [])
        lang = data.get("lang", "ru")
        
        full_text = f"{title}\n\nTags: {', '.join(tags)}\n\n{body}"
        
        # 1. Google Drive (Версионирование)
        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)
        upload_or_update_gdoc(service, title, full_text, lang)
        
        # 2. Локальный блог (Транслитерация имени)
        output_dir = os.path.join(BLOG_ROOT_DIR, "content", lang, "posts")
        os.makedirs(output_dir, exist_ok=True)
        
        # Генерируем "безопасное" имя файла для веба
        safe_filename = transliterate(title) + ".md"
        blog_filename = os.path.join(output_dir, safe_filename)
        
        from datetime import datetime
        date_now = datetime.now().strftime("%Y-%m-%d")

        with open(blog_filename, "w", encoding="utf-8") as f:
            f.write(f"---\n")
            f.write(f"title: \"{title}\"\n") # В заголовке остается кириллица
            f.write(f"date: {date_now}\n")
            f.write(f"tags: {json.dumps(tags, ensure_ascii=False)}\n")
            f.write(f"---\n\n")
            f.write(body)
            
        print(f"Локальный файл: {blog_filename}")
        
        # 3. Публикация
        git_push_changes(f"Post update: {title}")

    except Exception as e:
        print(f"Критическая ошибка: {e}")

if __name__ == '__main__':
    main()

