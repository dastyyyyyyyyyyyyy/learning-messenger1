import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
DATABASE = Path(os.environ.get(
    "MESSENGER_DB", str(Path(__file__).with_name("messenger.db"))
))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
SESSION_TTL = 12 * 60 * 60
PASSWORD_ITERATIONS = 310_000
sessions = {}
sessions_lock = threading.Lock()


PAGE = """<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Мессенджер</title>
    <style>
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            display: grid;
            place-items: center;
            background: #dce5ed;
            color: #17212b;
            font-family: Arial, sans-serif;
        }
        button, input { font: inherit; }
        button { cursor: pointer; }
        .hidden { display: none !important; }
        .auth {
            width: min(390px, calc(100% - 28px));
            padding: 28px;
            border-radius: 18px;
            background: white;
            box-shadow: 0 12px 40px #17212b20;
        }
        .auth h1 { margin-top: 0; color: #2481cc; }
        .auth label { display: block; margin-top: 15px; }
        .auth input, .auth button {
            width: 100%;
            min-height: 44px;
            margin-top: 7px;
            padding: 10px 12px;
            border: 1px solid #d5dfe8;
            border-radius: 10px;
        }
        .primary {
            border: 0 !important;
            background: #3390ec;
            color: white;
            font-weight: bold;
        }
        .link-button {
            border: 0 !important;
            background: transparent;
            color: #2481cc;
        }
        .notice { min-height: 22px; color: #bd3b44; }
        .chat-app {
            width: min(1120px, 100%);
            height: min(760px, 100vh);
            min-height: 480px;
            display: grid;
            grid-template-columns: 320px 1fr;
            overflow: hidden;
            background: white;
            box-shadow: 0 10px 40px #17212b20;
        }
        .sidebar {
            min-width: 0;
            display: flex;
            flex-direction: column;
            border-right: 1px solid #e6ebef;
        }
        .sidebar-top {
            padding: 16px;
            background: #f5f7f8;
        }
        .sidebar-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }
        .sidebar-title h1 { margin: 0; font-size: 20px; color: #2481cc; }
        .sidebar-top input {
            width: 100%;
            margin-top: 14px;
            padding: 10px 14px;
            border: 0;
            border-radius: 18px;
            background: #e9eef2;
        }
        .user-list { flex: 1; overflow-y: auto; }
        .user-row {
            width: 100%;
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 15px;
            border: 0;
            background: white;
            text-align: left;
        }
        .user-row:hover, .user-row.selected { background: #eef6fc; }
        .avatar {
            width: 46px;
            height: 46px;
            flex: 0 0 46px;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background: #68a9dc;
            color: white;
            font-size: 20px;
        }
        .user-info { min-width: 0; }
        .user-name { font-weight: bold; }
        .user-last {
            max-width: 220px;
            margin-top: 4px;
            overflow: hidden;
            color: #71808e;
            font-size: 13px;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .chat {
            min-width: 0;
            display: flex;
            flex-direction: column;
            background: #e8edf1;
            background-image: radial-gradient(#d3dce2 0.7px, transparent 0.7px);
            background-size: 18px 18px;
        }
        .chat-header {
            min-height: 66px;
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 18px;
            background: white;
            box-shadow: 0 1px 3px #17212b12;
        }
        .chat-header strong { display: block; }
        .chat-header small { display: block; margin-top: 4px; color: #71808e; }
        .messages {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 8px;
            overflow-y: auto;
            padding: 18px max(16px, 6%);
        }
        .bubble {
            max-width: min(75%, 520px);
            padding: 9px 12px 6px;
            border-radius: 12px;
            background: white;
            box-shadow: 0 1px 2px #17212b12;
            overflow-wrap: anywhere;
        }
        .bubble.mine {
            align-self: flex-end;
            background: #d9fdd3;
        }
        .bubble-time {
            margin-top: 5px;
            color: #71808e;
            font-size: 11px;
            text-align: right;
        }
        .empty-chat {
            margin: auto;
            padding: 10px 16px;
            border-radius: 16px;
            background: #dce6ec;
            color: #536675;
            text-align: center;
        }
        .composer {
            display: flex;
            gap: 10px;
            padding: 12px 16px;
            background: #f5f7f8;
        }
        .composer input {
            min-width: 0;
            flex: 1;
            padding: 12px 16px;
            border: 0;
            border-radius: 22px;
            outline-color: #3390ec;
        }
        .composer button {
            width: 46px;
            height: 46px;
            border: 0;
            border-radius: 50%;
            background: #3390ec;
            color: white;
            font-size: 20px;
        }
        .mobile-back { display: none; }
        @media (max-width: 650px) {
            body { display: block; }
            .chat-app { height: 100dvh; min-height: 0; grid-template-columns: 1fr; }
            .chat-app.chat-open .sidebar { display: none; }
            .chat-app:not(.chat-open) .chat { display: none; }
            .mobile-back {
                display: inline-grid;
                width: 36px;
                height: 36px;
                place-items: center;
                border: 0;
                border-radius: 50%;
                background: transparent;
                color: #2481cc;
                font-size: 22px;
            }
        }
    </style>
</head>
<body>
    <section id="authView" class="auth">
        <h1>Мессенджер</h1>
        <p>Открытая демо-версия: данные могут пропасть. Не используй настоящий пароль и не отправляй личные данные.</p>
        <form id="authForm">
            <label for="authUsername">Имя пользователя</label>
            <input id="authUsername" minlength="3" maxlength="20" required
                   autocomplete="username" placeholder="Например, sasha_1">
            <label for="authPassword">Пароль</label>
            <input id="authPassword" type="password" minlength="8" maxlength="128"
                   required autocomplete="current-password" placeholder="Не короче 8 символов">
            <button id="authSubmit" class="primary" type="submit">Войти</button>
        </form>
        <button id="authToggle" class="link-button" type="button">Создать аккаунт</button>
        <p id="authNotice" class="notice" role="status"></p>
    </section>

    <main id="chatApp" class="chat-app hidden">
        <aside class="sidebar">
            <div class="sidebar-top">
                <div class="sidebar-title">
                    <h1>Сообщения</h1>
                    <button id="logoutButton" class="link-button" type="button">Выйти</button>
                </div>
                <input id="userSearch" type="search" placeholder="Найти пользователя"
                       aria-label="Найти пользователя">
            </div>
            <div id="userList" class="user-list"></div>
        </aside>
        <section class="chat">
            <header class="chat-header">
                <button id="backButton" class="mobile-back" type="button" aria-label="Назад">‹</button>
                <div id="chatAvatar" class="avatar">?</div>
                <div>
                    <strong id="chatTitle">Выбери собеседника</strong>
                    <small id="chatSubtitle">Личные сообщения</small>
                </div>
            </header>
            <div id="messages" class="messages" aria-live="polite">
                <div class="empty-chat">Выбери пользователя слева, чтобы открыть переписку.</div>
            </div>
            <form id="messageForm" class="composer hidden">
                <input id="messageInput" maxlength="1000" autocomplete="off"
                       placeholder="Сообщение" aria-label="Сообщение" required>
                <button type="submit" aria-label="Отправить">➤</button>
            </form>
        </section>
    </main>

    <script>
        const authView = document.getElementById("authView");
        const authForm = document.getElementById("authForm");
        const authNotice = document.getElementById("authNotice");
        const authToggle = document.getElementById("authToggle");
        const authSubmit = document.getElementById("authSubmit");
        const authUsername = document.getElementById("authUsername");
        const authPassword = document.getElementById("authPassword");
        const chatApp = document.getElementById("chatApp");
        const userList = document.getElementById("userList");
        const messagesBox = document.getElementById("messages");
        const messageForm = document.getElementById("messageForm");
        const messageInput = document.getElementById("messageInput");
        const chatTitle = document.getElementById("chatTitle");
        const chatSubtitle = document.getElementById("chatSubtitle");
        const chatAvatar = document.getElementById("chatAvatar");
        let isRegistering = false;
        let currentUser = null;
        let activeChat = null;
        let lastMessageId = 0;
        let pollTimer = null;
        let loadingMessages = false;
        let knownUsers = [];

        async function api(path, options) {
            const response = await fetch(path, options);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Запрос не выполнен.");
            return data;
        }

        function showAuth(message) {
            currentUser = null;
            activeChat = null;
            chatApp.classList.add("hidden");
            authView.classList.remove("hidden");
            authNotice.textContent = message || "";
            if (pollTimer) window.clearTimeout(pollTimer);
        }

        function showChatApp(user) {
            currentUser = user;
            authView.classList.add("hidden");
            chatApp.classList.remove("hidden");
            document.getElementById("userSearch").value = "";
            refreshUsers();
        }

        authToggle.addEventListener("click", function () {
            isRegistering = !isRegistering;
            authSubmit.textContent = isRegistering ? "Создать аккаунт" : "Войти";
            authToggle.textContent = isRegistering ? "Уже есть аккаунт? Войти" : "Создать аккаунт";
            authPassword.autocomplete = isRegistering ? "new-password" : "current-password";
            authNotice.textContent = "";
        });

        authForm.addEventListener("submit", async function (event) {
            event.preventDefault();
            authSubmit.disabled = true;
            authNotice.textContent = "Проверяю данные...";
            try {
                const user = await api(isRegistering ? "/api/register" : "/api/login", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        username: authUsername.value.trim(),
                        password: authPassword.value
                    })
                });
                authPassword.value = "";
                showChatApp(user);
            } catch (error) {
                authNotice.textContent = error.message;
            } finally {
                authSubmit.disabled = false;
            }
        });

        async function refreshUsers() {
            try {
                knownUsers = await api("/api/users");
                renderUsers();
            } catch (error) {
                if (error.message === "Нужно войти в аккаунт.") showAuth(error.message);
            }
        }

        function renderUsers() {
            const query = document.getElementById("userSearch").value.trim().toLowerCase();
            userList.replaceChildren();
            const filtered = knownUsers.filter(user => user.username.toLowerCase().includes(query));

            if (filtered.length === 0) {
                const empty = document.createElement("p");
                empty.className = "empty-chat";
                empty.textContent = query ? "Пользователи не найдены." : "Пока нет других пользователей. Создай ещё один аккаунт в другом окне.";
                userList.append(empty);
                return;
            }

            for (const user of filtered) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "user-row" + (activeChat === user.username ? " selected" : "");
                const avatar = document.createElement("span");
                avatar.className = "avatar";
                avatar.textContent = user.username.charAt(0).toUpperCase();
                const info = document.createElement("span");
                info.className = "user-info";
                const name = document.createElement("span");
                name.className = "user-name";
                name.textContent = user.username;
                const preview = document.createElement("span");
                preview.className = "user-last";
                preview.textContent = user.last_message || "Начать переписку";
                info.append(name, preview);
                button.append(avatar, info);
                button.addEventListener("click", function () {
                    openChat(user.username);
                });
                userList.append(button);
            }
        }

        async function openChat(username) {
            if (pollTimer) window.clearTimeout(pollTimer);
            activeChat = username;
            lastMessageId = 0;
            chatTitle.textContent = username;
            chatSubtitle.textContent = "Личные сообщения";
            chatAvatar.textContent = username.charAt(0).toUpperCase();
            messageForm.classList.remove("hidden");
            chatApp.classList.add("chat-open");
            renderUsers();
            messagesBox.replaceChildren();
            await loadMessages(true);
            messageInput.focus();
        }

        function appendMessage(message) {
            const bubble = document.createElement("article");
            bubble.className = "bubble" + (message.sender === currentUser.username ? " mine" : "");
            const text = document.createElement("div");
            text.textContent = message.text;
            const time = document.createElement("div");
            time.className = "bubble-time";
            time.textContent = message.time;
            bubble.append(text, time);
            messagesBox.append(bubble);
        }

        async function loadMessages(initial) {
            if (!activeChat || loadingMessages) return;
            const requestedChat = activeChat;
            loadingMessages = true;
            try {
                const params = new URLSearchParams({
                    with: requestedChat,
                    after: initial ? "0" : String(lastMessageId)
                });
                const newMessages = await api("/api/messages?" + params.toString());
                if (requestedChat !== activeChat) return;
                for (const message of newMessages) {
                    appendMessage(message);
                    lastMessageId = Math.max(lastMessageId, message.id);
                }
                if (newMessages.length > 0) messagesBox.scrollTop = messagesBox.scrollHeight;
            } catch (error) {
                if (error.message === "Нужно войти в аккаунт.") showAuth(error.message);
            } finally {
                loadingMessages = false;
                if (requestedChat && requestedChat === activeChat) {
                    pollTimer = window.setTimeout(function () { loadMessages(false); }, 1200);
                }
            }
        }

        messageForm.addEventListener("submit", async function (event) {
            event.preventDefault();
            const text = messageInput.value.trim();
            if (!text || !activeChat) return;
            const submit = messageForm.querySelector("button");
            submit.disabled = true;
            try {
                await api("/api/messages", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ to: activeChat, text })
                });
                messageInput.value = "";
                await loadMessages(false);
                await refreshUsers();
                messageInput.focus();
            } catch (error) {
                window.alert(error.message);
            } finally {
                submit.disabled = false;
            }
        });

        document.getElementById("userSearch").addEventListener("input", renderUsers);
        document.getElementById("backButton").addEventListener("click", function () {
            chatApp.classList.remove("chat-open");
        });

        document.getElementById("logoutButton").addEventListener("click", async function () {
            try {
                await api("/api/logout", { method: "POST" });
            } finally {
                showAuth("Ты вышел из аккаунта.");
            }
        });

        api("/api/me")
            .then(showChatApp)
            .catch(function () { showAuth(""); });
    </script>
</body>
</html>
"""


@contextmanager
def connect_database():
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    with connect_database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL REFERENCES users(id),
                recipient_id INTEGER NOT NULL REFERENCES users(id),
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_between_users
                ON messages(sender_id, recipient_id, id);
            """
        )


def make_password_hash(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )


def valid_origin(handler):
    origin = handler.headers.get("Origin")
    return origin is not None and urlparse(origin).netloc == handler.headers.get("Host")


class ChatHandler(BaseHTTPRequestHandler):
    def send_json(self, status_code, data, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for name, value in extra_headers:
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_page(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 8192:
                raise ValueError("Размер запроса неправильный.")
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Не удалось прочитать данные формы."})
            return None
        if not isinstance(data, dict):
            self.send_json(400, {"error": "Ожидались данные формы."})
            return None
        return data

    def get_session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["session"].value
        except (KeyError, ValueError):
            return None

        now = time.time()
        with sessions_lock:
            session = sessions.get(token)
            if session is None:
                return None
            if session["expires"] < now:
                del sessions[token]
                return None
            session["expires"] = now + SESSION_TTL
            return session["user_id"]

    def set_session(self, user_id):
        token = secrets.token_urlsafe(32)
        with sessions_lock:
            sessions[token] = {"user_id": user_id, "expires": time.time() + SESSION_TTL}
        cookie = "session=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%s" % (
            token, SESSION_TTL
        )
        if COOKIE_SECURE:
            cookie += "; Secure"
        return [("Set-Cookie", cookie)]

    def clear_session(self):
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        token = cookie["session"].value if "session" in cookie else None
        if token:
            with sessions_lock:
                sessions.pop(token, None)
        return [("Set-Cookie", "session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")]

    def do_GET(self):
        path = urlparse(self.path)
        if path.path == "/":
            self.send_page()
            return

        user_id = self.get_session()
        if user_id is None:
            self.send_json(401, {"error": "Нужно войти в аккаунт."})
            return

        if path.path == "/api/me":
            with connect_database() as connection:
                user = connection.execute(
                    "SELECT id, username FROM users WHERE id = ?", (user_id,)
                ).fetchone()
            if user is None:
                self.send_json(401, {"error": "Аккаунт не найден."})
            else:
                self.send_json(200, {"id": user["id"], "username": user["username"]})
            return

        if path.path == "/api/users":
            with connect_database() as connection:
                rows = connection.execute(
                    """
                    SELECT u.id, u.username,
                        (SELECT m.text FROM messages m
                         WHERE (m.sender_id = ? AND m.recipient_id = u.id)
                            OR (m.sender_id = u.id AND m.recipient_id = ?)
                         ORDER BY m.id DESC LIMIT 1) AS last_message
                    FROM users u
                    WHERE u.id != ?
                    ORDER BY u.username COLLATE NOCASE
                    """,
                    (user_id, user_id, user_id),
                ).fetchall()
            self.send_json(200, [
                {"id": row["id"], "username": row["username"],
                 "last_message": row["last_message"] or ""}
                for row in rows
            ])
            return

        if path.path == "/api/messages":
            query = parse_qs(path.query)
            recipient_name = query.get("with", [""])[0]
            try:
                after_id = max(0, int(query.get("after", ["0"])[0]))
            except ValueError:
                self.send_json(400, {"error": "Неверный номер сообщения."})
                return

            with connect_database() as connection:
                recipient = connection.execute(
                    "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                    (recipient_name,),
                ).fetchone()
                if recipient is None or recipient["id"] == user_id:
                    self.send_json(404, {"error": "Собеседник не найден."})
                    return
                rows = connection.execute(
                    """
                    SELECT m.id, m.sender_id, sender.username AS sender,
                           m.text, m.created_at
                    FROM messages m
                    JOIN users sender ON sender.id = m.sender_id
                    WHERE m.id > ? AND (
                        (m.sender_id = ? AND m.recipient_id = ?)
                        OR (m.sender_id = ? AND m.recipient_id = ?)
                    )
                    ORDER BY m.id DESC
                    LIMIT 100
                    """,
                    (after_id, user_id, recipient["id"], recipient["id"], user_id),
                ).fetchall()
            self.send_json(200, [
                {"id": row["id"], "sender": row["sender"], "text": row["text"],
                 "time": row["created_at"]}
                for row in reversed(rows)
            ])
            return

        self.send_json(404, {"error": "Страница не найдена."})

    def do_POST(self):
        if not valid_origin(self):
            self.send_json(403, {"error": "Запрос отклонён: неверный источник."})
            return

        path = urlparse(self.path).path
        if path == "/api/logout":
            self.send_json(200, {"ok": True}, self.clear_session())
            return

        data = self.read_json()
        if data is None:
            return

        if path in ("/api/register", "/api/login"):
            username = data.get("username")
            password = data.get("password")
            if not isinstance(username, str) or not isinstance(password, str):
                self.send_json(400, {"error": "Введи имя пользователя и пароль."})
                return

            username = username.strip()
            if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
                self.send_json(400, {
                    "error": "Имя: 3–20 символов, только латинские буквы, цифры и _."
                })
                return
            if len(password) < 8 or len(password) > 128:
                self.send_json(400, {"error": "Пароль должен содержать от 8 до 128 символов."})
                return

            with connect_database() as connection:
                user = connection.execute(
                    "SELECT id, username, password_salt, password_hash "
                    "FROM users WHERE username = ? COLLATE NOCASE",
                    (username,),
                ).fetchone()
                if path == "/api/register":
                    if user is not None:
                        self.send_json(409, {"error": "Это имя уже занято."})
                        return
                    salt = secrets.token_bytes(16)
                    password_hash = make_password_hash(password, salt)
                    try:
                        cursor = connection.execute(
                            "INSERT INTO users (username, password_salt, password_hash) "
                            "VALUES (?, ?, ?)",
                            (username, salt, password_hash),
                        )
                    except sqlite3.IntegrityError:
                        self.send_json(409, {"error": "Это имя уже занято."})
                        return
                    user_id = cursor.lastrowid
                    saved_username = username
                else:
                    if user is None:
                        self.send_json(401, {"error": "Неверное имя или пароль."})
                        return
                    candidate = make_password_hash(password, user["password_salt"])
                    if not hmac.compare_digest(candidate, user["password_hash"]):
                        self.send_json(401, {"error": "Неверное имя или пароль."})
                        return
                    user_id = user["id"]
                    saved_username = user["username"]

            headers = self.set_session(user_id)
            self.send_json(200, {"id": user_id, "username": saved_username}, headers)
            return

        if path == "/api/messages":
            user_id = self.get_session()
            if user_id is None:
                self.send_json(401, {"error": "Нужно войти в аккаунт."})
                return

            recipient_name = data.get("to")
            text = data.get("text")
            if not isinstance(recipient_name, str) or not isinstance(text, str):
                self.send_json(400, {"error": "Нужны имя собеседника и текст сообщения."})
                return
            recipient_name = recipient_name.strip()
            text = text.strip()
            if not text or len(text) > 1000:
                self.send_json(400, {"error": "Сообщение должно содержать от 1 до 1000 символов."})
                return

            with connect_database() as connection:
                recipient = connection.execute(
                    "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                    (recipient_name,),
                ).fetchone()
                if recipient is None or recipient["id"] == user_id:
                    self.send_json(404, {"error": "Собеседник не найден."})
                    return
                created_at = datetime.now().strftime("%H:%M")
                connection.execute(
                    "INSERT INTO messages (sender_id, recipient_id, text, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, recipient["id"], text, created_at),
                )
            self.send_json(201, {"ok": True})
            return

        self.send_json(404, {"error": "Страница не найдена."})

    def log_message(self, format_string, *args):
        print("%s - %s" % (self.address_string(), format_string % args))


def main():
    initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), ChatHandler)

    print("Учебный мессенджер запущен.")
    if HOST == "127.0.0.1":
        print("Открой в браузере: http://localhost:%s" % PORT)
        print("Сервер доступен только на этом компьютере.")
    else:
        print("Сервер слушает %s:%s" % (HOST, PORT))
    print("Остановить сервер можно сочетанием Ctrl+C.")
    print("Это демо: на бесплатном хостинге база может очищаться; не отправляй личные данные.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nЗавершаю работу мессенджера.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
