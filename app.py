from flask import Flask, render_template, request, redirect, url_for, session
from flask import jsonify
from datetime import datetime
from g4f.client import Client
import markdown
from markdown.extensions.fenced_code import FencedCodeExtension
from markupsafe import Markup
import re
import requests
from bs4 import BeautifulSoup
import urllib.parse
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
app.secret_key = 'SecretKeyUnlimChat-10292009!)('
app.static_folder = 'static'

def clean_text(text):
    text = re.sub(r'\s+', ' ', text)  # Удаляем множественные пробелы
    text = re.sub(r'\[.*?\]', '', text)  # Удаляем квадратные скобки с содержимым
    text = re.sub(r'\{.*?\}', '', text)  # Удаляем фигурные скобки с содержимым
    text = re.sub(r'<[^>]+>', '', text)  # Удаляем HTML-теги
    text = re.sub(r'[^\w\s.,!?;:()-]', '', text)  # Удаляем спецсимволы
    text = re.sub(r'\b\w{1,2}\b', '', text)  # Удаляем короткие слова
    text = re.sub(r'\s+', ' ', text).strip()  # Финальная очистка пробелов
    return text[:5000]  # Ограничиваем длину

def get_search_results(query):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Ищем в Google (меняем user-agent для обхода блокировки)
        url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Собираем первые 3 релевантных ссылки
        links = []
        for link in soup.select('a[href^="/url?q="]'):
            href = link['href']
            url = href.split('/url?q=')[1].split('&')[0]
            if 'google.com' not in url and url not in links:
                links.append(urllib.parse.unquote(url))
                if len(links) >= 3:
                    break
        
        # Парсим контент с найденных страниц
        content = ""
        for link in links:
            try:
                page_response = requests.get(link, headers=headers, timeout=15)
                page_soup = BeautifulSoup(page_response.text, 'html.parser')
                
                # Удаляем ненужные элементы
                for element in page_soup(['script', 'style', 'iframe', 'nav', 'footer', 'aside', 'form', 'img']):
                    element.decompose()
                
                # Получаем основной текст
                text = page_soup.get_text()
                text = clean_text(text)
                content += f"Источник: {link}\n{text[:2000]}\n\n"  # Берем первые 2000 символов
            except:
                continue
        
        return content if content else None
        
    except Exception as e:
        print(f"Search error: {e}")
        return None

def scrape_website(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')

        for element in soup(['script', 'style', 'iframe', 'nav', 'footer', 'aside', 'form', 'img']):
            element.decompose()

        text = soup.get_text()
        return clean_text(text)
    except Exception as e:
        print(f"Scraping error: {e}")
        return None

def format_latex_in_response(text):
    if not text:
        return ""
    text = re.sub(r'(\d+)(?=[A-Za-z]|$)', r'<sub>\1</sub>', text)
    text = re.sub(r'(?<=[A-Za-z])(\d+)', r'<sub>\1</sub>', text)
    text = re.sub(r'->|→', ' → ', text)
    text = re.sub(r'\+', ' + ', text)
    text = re.sub(r'\^(\d+)', r'<sup>\1</sup>', text)
    text = re.sub(r'\\frac{(.*?)}{(.*?)}', r'<span class="frac">\1⁄\2</span>', text)
    
    def wrap_math(match):
        expr = match.group(1)
        return f'<div class="math-equation">\\({expr}\\)</div>'
    
    text = re.sub(r'\$(.*?)\$', wrap_math, text)
    return Markup(text)

@app.template_filter('escape_quotes')
def escape_quotes(text):
    return text.replace('"', '&quot;').replace("'", "&apos;")

# Добавляем middleware для "анонимизации" логов
@app.after_request
def remove_ip_logging(response):
    # Убираем IP из логов Werkzeug
    if request.path == '/get_new_messages':
        # Подменяем реальный IP на "anonymous"
        environ = request.environ
        environ['REMOTE_ADDR'] = 'anonymous'
    return response

chat_messages = []
ai_chat_history = {}

class NoPollingLogsFilter(logging.Filter):
    def filter(self, record):
        # Игнорируем логи, содержащие путь /get_new_messages
        return "/get_new_messages" not in record.getMessage()

flask_logger = logging.getLogger('werkzeug')
flask_logger.addFilter(NoPollingLogsFilter())

flask_logger.setLevel(logging.ERROR)

@app.route('/get_new_messages')
def get_new_messages():
    last_index = int(request.args.get('last_index', 0))
    new_messages = chat_messages[last_index:]
    return jsonify({
        'messages': new_messages,
        'new_index': len(chat_messages)
    })

@app.route('/', methods=['GET', 'POST'])
def nickname():
    if request.method == 'POST':
        nickname = request.form.get('nickname')
        if nickname:
            session['nickname'] = nickname
            if nickname not in ai_chat_history:
                ai_chat_history[nickname] = []
            return redirect(url_for('chat'))
    return render_template('nickname.html')

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'nickname' not in session:
        return redirect(url_for('nickname'))
    
    if request.method == 'POST':
        message = request.form.get('message')
        if message:
            timestamp = datetime.now().strftime('%H:%M:%S')
            chat_messages.append({
                'nickname': session['nickname'],
                'message': message,
                'timestamp': timestamp
            })
            if len(chat_messages) > 100:
                chat_messages.pop(0)
            return redirect(url_for('chat'))
    
    return render_template('chat.html',
                         nickname=session['nickname'],
                         messages=chat_messages)

@app.route('/ai_chat', methods=['GET', 'POST'])
def ai_chat():
    if 'nickname' not in session:
        return redirect(url_for('nickname'))
    
    nickname = session['nickname']
    
    if nickname not in ai_chat_history:
        ai_chat_history[nickname] = []
    
    if request.method == 'POST':
        if 'toggle_web_search' in request.form:
            session['web_search'] = not session.get('web_search', False)
            return redirect(url_for('ai_chat'))
        
        if 'clear_history' in request.form:
            ai_chat_history[nickname] = []
            return redirect(url_for('ai_chat'))
        
        if 'generate_image' in request.form:
            image_prompt = request.form.get('image_prompt')
            if image_prompt and image_prompt.strip():
                try:
                    client = Client()
                    response = client.images.generate(
                        model="flux",
                        prompt=image_prompt.strip(),
                        response_format="url"
                    )
                    image_url = response.data[0].url
                    
                    ai_chat_history[nickname].extend([
                        {
                            "role": "user",
                            "content": f"Запрос изображения: {image_prompt}",
                            "timestamp": datetime.now().strftime('%H:%M:%S'),
                            "is_image_request": True
                        },
                        {
                            "role": "assistant",
                            "content": f"![Генерация изображения]({image_url})",
                            "timestamp": datetime.now().strftime('%H:%M:%S'),
                            "is_image": True,
                            "image_url": image_url
                        }
                    ])
                except Exception as e:
                    print(f"Image generation error: {str(e)}")
                    ai_chat_history[nickname].append({
                        "role": "assistant",
                        "content": "⚠️ Ошибка при генерации изображения",
                        "timestamp": datetime.now().strftime('%H:%M:%S')
                    })
                return redirect(url_for('ai_chat'))
        
        user_message = request.form.get('message')
        if user_message and user_message.strip():
            messages_for_ai = [{"role": "system", "content": "You are a helpful assistant."}]
            
            for msg in ai_chat_history[nickname]:
                if not msg.get('is_image') and not msg.get('is_image_request'):
                    messages_for_ai.append({
                        "role": msg['role'],
                        "content": msg['content']
                    })
            
            messages_for_ai.append({"role": "user", "content": user_message.strip()})
            
            try:
                client = Client()
                web_content = None
                
                if session.get('web_search'):
                    web_content = get_search_results(user_message)
                    print(f"Получен контент: {web_content}...")  # Логируем для отладки

                # Формируем промпт для ИИ
                prompt = (
                    f"Пользователь спросил: {user_message}\n\n" +
                    (f"Вот информация из интернета:\n{web_content}\n\n" if web_content else "") +
                    "Дай максимально точный и развернутый ответ на вопрос пользователя, " +
                    "используя предоставленные данные (если они есть). " +
                    "Если информации недостаточно, скажи об этом честно."
                )
                
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}]
                )
                
                ai_response = response.choices[0].message.content
                formatted_response = format_latex_in_response(ai_response)
                
                ai_chat_history[nickname].extend([
                    {
                        "role": "user",
                        "content": user_message.strip(),
                        "timestamp": datetime.now().strftime('%H:%M:%S'),
                        "used_web_search": session.get('web_search', False)
                    },
                    {
                        "role": "assistant",
                        "content": markdown.markdown(
                            formatted_response,
                            extensions=[FencedCodeExtension()]
                        ),
                        "timestamp": datetime.now().strftime('%H:%M:%S'),
                        "used_web_search": session.get('web_search', False)
                    }
                ])
                
                if len(ai_chat_history[nickname]) > 40:
                    ai_chat_history[nickname] = ai_chat_history[nickname][-40:]
                    
            except Exception as e:
                print(f"AI Error: {str(e)}")
                ai_chat_history[nickname].append({
                    "role": "assistant",
                    "content": "⚠️ Ошибка обработки запроса",
                    "timestamp": datetime.now().strftime('%H:%M:%S')
                })
            
            return redirect(url_for('ai_chat'))
    
    return render_template('ai_chat.html',
                        nickname=nickname,
                        messages=ai_chat_history.get(nickname, []),
                        web_search=session.get('web_search', False))

@app.route('/clear_ai_history', methods=['POST'])
def clear_ai_history():
    if 'nickname' not in session:
        return redirect(url_for('nickname'))
    
    nickname = session['nickname']
    if nickname in ai_chat_history:
        ai_chat_history[nickname] = []
    
    return redirect(url_for('ai_chat'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)