"""
Heuchelberger Warte Chatbot - Mecki
FastAPI Backend mit HTML Test-Interface
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager

# Umgebungsvariablen laden
load_dotenv()

# Imports nach dem Laden der Umgebungsvariablen
from bot_logic import generate_response, get_token_stats, reset_token_stats
from database import (
    init_database,
    get_or_create_session,
    log_message,
    get_chat_history,
    get_all_chats,
    set_bot_status,
    get_bot_status,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialisierung beim Start."""
    await init_database()
    print("Datenbank initialisiert")
    print("Mecki Chatbot gestartet!")
    yield
    print("Chatbot beendet.")


app = FastAPI(
    title="Mecki - Heuchelberger Warte Chatbot",
    description="Service Chatbot für die Heuchelberger Warte",
    version="1.0.0",
    lifespan=lifespan
)


# Request/Response Models
class ChatMessage(BaseModel):
    message: str
    user_id: str = "test_user"
    is_new_session: bool = False


class ChatResponse(BaseModel):
    response: str
    token_stats: dict
    total_stats: dict


class BotStatusUpdate(BaseModel):
    user_id: str
    active: bool


# ============================================================================
# API Endpoints
# ============================================================================

@app.post("/api/chat", response_model=ChatResponse)
async def chat(message: ChatMessage):
    """Hauptendpunkt für Chat-Nachrichten."""

    # Session prüfen
    session = await get_or_create_session(message.user_id)

    # Prüfen ob Bot für diesen Nutzer aktiv ist (Human-in-the-Loop)
    if not session["bot_active"]:
        return ChatResponse(
            response="[Bot pausiert - Mensch übernimmt]",
            token_stats={"input_tokens": 0, "output_tokens": 0},
            total_stats=get_token_stats()
        )

    # Nachricht loggen
    await log_message(message.user_id, message.message, "user")

    # Chat-Historie für Kontext holen
    history = await get_chat_history(message.user_id, limit=10)

    # Antwort generieren
    response_text, token_stats = await generate_response(
        user_message=message.message,
        is_new_session=session["is_new_session"],
        conversation_history=history
    )

    # Bot-Antwort loggen
    await log_message(message.user_id, response_text, "bot")

    return ChatResponse(
        response=response_text,
        token_stats=token_stats,
        total_stats=get_token_stats()
    )


@app.get("/api/stats")
async def get_stats():
    """Gibt Token-Statistiken zurück."""
    return get_token_stats()


@app.post("/api/stats/reset")
async def reset_stats():
    """Setzt Token-Statistiken zurück."""
    reset_token_stats()
    return {"status": "reset", "stats": get_token_stats()}


@app.get("/api/chats")
async def list_chats():
    """Listet alle Chat-Sessions auf."""
    chats = await get_all_chats()
    return {"chats": chats}


@app.get("/api/chat/{user_id}/history")
async def get_history(user_id: str):
    """Holt Chat-Historie für einen Nutzer."""
    history = await get_chat_history(user_id, limit=100)
    return {"history": history}


@app.post("/api/bot/status")
async def update_bot_status(status: BotStatusUpdate):
    """Setzt Bot-Status (aktiv/inaktiv) für Human-in-the-Loop."""
    await set_bot_status(status.user_id, status.active)
    return {"user_id": status.user_id, "bot_active": status.active}


@app.get("/api/bot/status/{user_id}")
async def get_status(user_id: str):
    """Prüft Bot-Status für einen Nutzer."""
    active = await get_bot_status(user_id)
    return {"user_id": user_id, "bot_active": active}


# ============================================================================
# HTML Interface
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """Hauptseite mit Chat-Interface und Token-Dashboard."""
    html_content = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mecki - Heuchelberger Warte Chatbot</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
        }

        .container {
            display: grid;
            grid-template-columns: 1fr 320px;
            gap: 20px;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            height: 100vh;
        }

        /* Chat Section */
        .chat-section {
            display: flex;
            flex-direction: column;
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            overflow: hidden;
        }

        .chat-header {
            background: linear-gradient(135deg, #4a7c59 0%, #3d6b4f 100%);
            padding: 20px;
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .chat-header .avatar {
            width: 50px;
            height: 50px;
            background: #fff;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
        }

        .chat-header h1 {
            font-size: 1.5rem;
            font-weight: 600;
        }

        .chat-header p {
            opacity: 0.8;
            font-size: 0.9rem;
        }

        .chat-messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 15px;
        }

        .message {
            max-width: 80%;
            padding: 12px 16px;
            border-radius: 16px;
            line-height: 1.5;
            animation: fadeIn 0.3s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .message.user {
            background: #4a7c59;
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }

        .message.bot {
            background: rgba(255,255,255,0.1);
            align-self: flex-start;
            border-bottom-left-radius: 4px;
        }

        .message a {
            color: #7dd3fc;
            word-break: break-all;
        }

        .message .timestamp {
            font-size: 0.7rem;
            opacity: 0.6;
            margin-top: 5px;
        }

        .chat-input {
            padding: 20px;
            background: rgba(0,0,0,0.2);
            display: flex;
            gap: 10px;
        }

        .chat-input input {
            flex: 1;
            padding: 15px 20px;
            border: none;
            border-radius: 25px;
            background: rgba(255,255,255,0.1);
            color: #fff;
            font-size: 1rem;
            outline: none;
        }

        .chat-input input::placeholder {
            color: rgba(255,255,255,0.5);
        }

        .chat-input button {
            padding: 15px 30px;
            border: none;
            border-radius: 25px;
            background: #4a7c59;
            color: #fff;
            font-size: 1rem;
            cursor: pointer;
            transition: background 0.2s;
        }

        .chat-input button:hover {
            background: #5a9c69;
        }

        .chat-input button:disabled {
            background: #666;
            cursor: not-allowed;
        }

        /* Stats Section */
        .stats-section {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }

        .stats-card {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
        }

        .stats-card h2 {
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            opacity: 0.7;
            margin-bottom: 15px;
        }

        .stat-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }

        .stat-row:last-child {
            border-bottom: none;
        }

        .stat-label {
            opacity: 0.7;
        }

        .stat-value {
            font-weight: 600;
            font-family: 'Monaco', monospace;
        }

        .stat-value.highlight {
            color: #4ade80;
            font-size: 1.2rem;
        }

        .cost-display {
            text-align: center;
            padding: 20px 0;
        }

        .cost-display .amount {
            font-size: 2.5rem;
            font-weight: 700;
            color: #4ade80;
        }

        .cost-display .currency {
            font-size: 1rem;
            opacity: 0.7;
        }

        .reset-btn {
            width: 100%;
            padding: 12px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 8px;
            background: transparent;
            color: #fff;
            cursor: pointer;
            transition: all 0.2s;
        }

        .reset-btn:hover {
            background: rgba(255,255,255,0.1);
        }

        /* Last Request Stats */
        .last-request {
            background: rgba(74, 124, 89, 0.2);
            border: 1px solid rgba(74, 124, 89, 0.3);
        }

        /* Quick Actions */
        .quick-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
        }

        .quick-btn {
            padding: 8px 12px;
            background: rgba(255,255,255,0.1);
            border: none;
            border-radius: 20px;
            color: #fff;
            font-size: 0.85rem;
            cursor: pointer;
            transition: background 0.2s;
        }

        .quick-btn:hover {
            background: rgba(255,255,255,0.2);
        }

        /* Typing indicator */
        .typing {
            display: flex;
            gap: 5px;
            padding: 15px;
            background: rgba(255,255,255,0.1);
            border-radius: 16px;
            width: fit-content;
        }

        .typing span {
            width: 8px;
            height: 8px;
            background: #fff;
            border-radius: 50%;
            animation: bounce 1.4s infinite ease-in-out;
        }

        .typing span:nth-child(1) { animation-delay: 0s; }
        .typing span:nth-child(2) { animation-delay: 0.2s; }
        .typing span:nth-child(3) { animation-delay: 0.4s; }

        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0); opacity: 0.5; }
            40% { transform: scale(1); opacity: 1; }
        }

        /* Responsive */
        @media (max-width: 900px) {
            .container {
                grid-template-columns: 1fr;
                grid-template-rows: 1fr auto;
            }
            .stats-section {
                flex-direction: row;
                flex-wrap: wrap;
            }
            .stats-card {
                flex: 1;
                min-width: 200px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Chat Section -->
        <div class="chat-section">
            <div class="chat-header">
                <div class="avatar">🦔</div>
                <div>
                    <h1>Mecki</h1>
                    <p>Heuchelberger Warte Chatbot</p>
                </div>
            </div>

            <div class="chat-messages" id="chatMessages">
                <div class="message bot">
                    Hi, ich bin's Mecki, der Heuchelberg Chat Bot :)
                    <div class="timestamp">Jetzt</div>
                </div>
            </div>

            <div class="chat-input">
                <input type="text" id="messageInput" placeholder="Schreib mir eine Nachricht..." autofocus>
                <button id="sendBtn" onclick="sendMessage()">Senden</button>
            </div>

            <div style="padding: 10px 20px; background: rgba(0,0,0,0.1);">
                <div class="quick-actions">
                    <button class="quick-btn" onclick="quickSend('Öffnungszeiten?')">Öffnungszeiten</button>
                    <button class="quick-btn" onclick="quickSend('Wie kann ich reservieren?')">Reservierung</button>
                    <button class="quick-btn" onclick="quickSend('Wo kann ich parken?')">Parken</button>
                    <button class="quick-btn" onclick="quickSend('Gibt es einen Shuttle?')">Shuttle</button>
                    <button class="quick-btn" onclick="quickSend('Wir möchten eine Hochzeit feiern')">Hochzeit</button>
                </div>
            </div>
        </div>

        <!-- Stats Section -->
        <div class="stats-section">
            <!-- Kosten Total -->
            <div class="stats-card">
                <h2>Session Kosten</h2>
                <div class="cost-display">
                    <div class="amount" id="totalCostEur">0.000000</div>
                    <div class="currency">EUR</div>
                </div>
                <div class="stat-row">
                    <span class="stat-label">USD</span>
                    <span class="stat-value" id="totalCostUsd">$0.000000</span>
                </div>
            </div>

            <!-- Token Stats -->
            <div class="stats-card">
                <h2>Token Verbrauch</h2>
                <div class="stat-row">
                    <span class="stat-label">Input Tokens</span>
                    <span class="stat-value" id="totalInputTokens">0</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Output Tokens</span>
                    <span class="stat-value" id="totalOutputTokens">0</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Total Tokens</span>
                    <span class="stat-value highlight" id="totalTokens">0</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Nachrichten</span>
                    <span class="stat-value" id="messageCount">0</span>
                </div>
            </div>

            <!-- Letzte Anfrage -->
            <div class="stats-card last-request">
                <h2>Letzte Anfrage</h2>
                <div class="stat-row">
                    <span class="stat-label">Input</span>
                    <span class="stat-value" id="lastInputTokens">-</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Output</span>
                    <span class="stat-value" id="lastOutputTokens">-</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Kosten</span>
                    <span class="stat-value" id="lastCost">-</span>
                </div>
            </div>

            <!-- Actions -->
            <div class="stats-card">
                <h2>Aktionen</h2>
                <button class="reset-btn" onclick="resetStats()">
                    🔄 Statistiken zurücksetzen
                </button>
                <button class="reset-btn" style="margin-top: 10px;" onclick="clearChat()">
                    🗑️ Chat leeren
                </button>
            </div>
        </div>
    </div>

    <script>
        const userId = 'test_user_' + Date.now();
        const chatMessages = document.getElementById('chatMessages');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');

        // Enter zum Senden
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        async function sendMessage() {
            const message = messageInput.value.trim();
            if (!message) return;

            // User-Nachricht anzeigen
            addMessage(message, 'user');
            messageInput.value = '';
            sendBtn.disabled = true;

            // Typing Indicator
            const typing = showTyping();

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: message,
                        user_id: userId,
                        is_new_session: false
                    })
                });

                const data = await response.json();

                // Typing entfernen
                typing.remove();

                // Bot-Antwort anzeigen
                addMessage(data.response, 'bot');

                // Stats aktualisieren
                updateStats(data.total_stats, data.token_stats);

            } catch (error) {
                typing.remove();
                addMessage('Fehler: ' + error.message, 'bot');
            }

            sendBtn.disabled = false;
            messageInput.focus();
        }

        function quickSend(text) {
            messageInput.value = text;
            sendMessage();
        }

        function addMessage(text, sender) {
            const div = document.createElement('div');
            div.className = `message ${sender}`;

            // Links klickbar machen
            const linkedText = text.replace(
                /(https?:\\/\\/[^\\s]+)/g,
                '<a href="$1" target="_blank">$1</a>'
            );

            const time = new Date().toLocaleTimeString('de-DE', {
                hour: '2-digit',
                minute: '2-digit'
            });

            div.innerHTML = `
                ${linkedText}
                <div class="timestamp">${time}</div>
            `;

            chatMessages.appendChild(div);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        function showTyping() {
            const div = document.createElement('div');
            div.className = 'typing';
            div.innerHTML = '<span></span><span></span><span></span>';
            chatMessages.appendChild(div);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            return div;
        }

        function updateStats(totalStats, lastStats) {
            // Total Stats
            document.getElementById('totalCostEur').textContent =
                totalStats.total_cost_eur.toFixed(6);
            document.getElementById('totalCostUsd').textContent =
                '$' + totalStats.total_cost_usd.toFixed(6);
            document.getElementById('totalInputTokens').textContent =
                totalStats.input_tokens.toLocaleString();
            document.getElementById('totalOutputTokens').textContent =
                totalStats.output_tokens.toLocaleString();
            document.getElementById('totalTokens').textContent =
                totalStats.total_tokens.toLocaleString();
            document.getElementById('messageCount').textContent =
                totalStats.session_messages;

            // Last Request Stats
            if (lastStats && lastStats.input_tokens > 0) {
                document.getElementById('lastInputTokens').textContent =
                    lastStats.input_tokens.toLocaleString();
                document.getElementById('lastOutputTokens').textContent =
                    lastStats.output_tokens.toLocaleString();

                const lastCost = (lastStats.input_tokens / 1000 * 0.003) +
                                (lastStats.output_tokens / 1000 * 0.015);
                document.getElementById('lastCost').textContent =
                    '$' + lastCost.toFixed(6);
            }
        }

        async function resetStats() {
            await fetch('/api/stats/reset', { method: 'POST' });
            updateStats({
                total_cost_eur: 0,
                total_cost_usd: 0,
                input_tokens: 0,
                output_tokens: 0,
                total_tokens: 0,
                session_messages: 0
            }, null);
        }

        function clearChat() {
            chatMessages.innerHTML = `
                <div class="message bot">
                    Hi, ich bin's Mecki, der Heuchelberg Chat Bot :)
                    <div class="timestamp">Jetzt</div>
                </div>
            `;
        }

        // Initial Stats laden
        fetch('/api/stats').then(r => r.json()).then(data => {
            updateStats(data, null);
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


# ============================================================================
# Mobile Chat (zum Teilen)
# ============================================================================

@app.get("/chat", response_class=HTMLResponse)
async def mobile_chat():
    """Mobile Chat-Seite zum Teilen - ohne Statistiken."""
    html_content = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Mecki - Heuchelberger Warte</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🦔</text></svg>">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        html, body {
            height: 100%;
            overflow: hidden;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #2d5016 0%, #1a3009 100%);
            color: #fff;
        }

        .chat-container {
            display: flex;
            flex-direction: column;
            height: 100vh;
            height: 100dvh;
            max-width: 500px;
            margin: 0 auto;
            background: #1a1a1a;
        }

        .chat-header {
            background: linear-gradient(135deg, #4a7c59 0%, #3d6b4f 100%);
            padding: 15px 20px;
            display: flex;
            align-items: center;
            gap: 12px;
            flex-shrink: 0;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        }

        .avatar {
            width: 45px;
            height: 45px;
            background: #fff;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
        }

        .header-text h1 {
            font-size: 1.1rem;
            font-weight: 600;
        }

        .header-text p {
            font-size: 0.8rem;
            opacity: 0.85;
        }

        .chat-messages {
            flex: 1;
            overflow-y: auto;
            padding: 15px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background: #0d1f0d;
        }

        .message {
            max-width: 85%;
            padding: 10px 14px;
            border-radius: 18px;
            line-height: 1.4;
            font-size: 0.95rem;
            animation: fadeIn 0.3s ease;
            word-wrap: break-word;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .message.user {
            background: #4a7c59;
            align-self: flex-end;
            border-bottom-right-radius: 6px;
        }

        .message.bot {
            background: #2a2a2a;
            align-self: flex-start;
            border-bottom-left-radius: 6px;
        }

        .message a {
            color: #7dd3fc;
            word-break: break-all;
        }

        .message .time {
            font-size: 0.65rem;
            opacity: 0.5;
            margin-top: 4px;
            display: block;
        }

        .chat-input-area {
            padding: 12px;
            background: #1a1a1a;
            border-top: 1px solid #333;
            flex-shrink: 0;
        }

        .input-row {
            display: flex;
            gap: 10px;
            align-items: center;
        }

        .chat-input-area input {
            flex: 1;
            padding: 12px 18px;
            border: none;
            border-radius: 24px;
            background: #2a2a2a;
            color: #fff;
            font-size: 1rem;
            outline: none;
        }

        .chat-input-area input::placeholder {
            color: #888;
        }

        .send-btn {
            width: 46px;
            height: 46px;
            border: none;
            border-radius: 50%;
            background: #4a7c59;
            color: #fff;
            font-size: 1.3rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s;
        }

        .send-btn:active {
            background: #3d6b4f;
        }

        .send-btn:disabled {
            background: #555;
        }

        .quick-btns {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            padding: 10px 0 5px 0;
            -webkit-overflow-scrolling: touch;
        }

        .quick-btns::-webkit-scrollbar {
            display: none;
        }

        .quick-btn {
            padding: 8px 14px;
            background: #2a2a2a;
            border: 1px solid #444;
            border-radius: 18px;
            color: #fff;
            font-size: 0.85rem;
            white-space: nowrap;
            cursor: pointer;
        }

        .quick-btn:active {
            background: #3a3a3a;
        }

        .typing {
            display: flex;
            gap: 4px;
            padding: 12px 16px;
            background: #2a2a2a;
            border-radius: 18px;
            width: fit-content;
            align-self: flex-start;
        }

        .typing span {
            width: 8px;
            height: 8px;
            background: #888;
            border-radius: 50%;
            animation: bounce 1.4s infinite ease-in-out;
        }

        .typing span:nth-child(1) { animation-delay: 0s; }
        .typing span:nth-child(2) { animation-delay: 0.2s; }
        .typing span:nth-child(3) { animation-delay: 0.4s; }

        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
            40% { transform: scale(1); opacity: 1; }
        }

        .powered-by {
            text-align: center;
            font-size: 0.7rem;
            color: #555;
            padding: 5px;
        }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <div class="avatar">🦔</div>
            <div class="header-text">
                <h1>Mecki</h1>
                <p>Heuchelberger Warte Chatbot</p>
            </div>
        </div>

        <div class="chat-messages" id="messages">
            <div class="message bot">
                Hi, ich bin's Mecki, der Heuchelberg Chat Bot 😊 Wie kann ich dir helfen?
                <span class="time">Jetzt</span>
            </div>
        </div>

        <div class="chat-input-area">
            <div class="quick-btns">
                <button class="quick-btn" onclick="send('Öffnungszeiten?')">Öffnungszeiten</button>
                <button class="quick-btn" onclick="send('Tisch reservieren')">Reservieren</button>
                <button class="quick-btn" onclick="send('Wo parken?')">Parken</button>
                <button class="quick-btn" onclick="send('Shuttle?')">Shuttle</button>
            </div>
            <div class="input-row">
                <input type="text" id="input" placeholder="Nachricht schreiben..." autocomplete="off">
                <button class="send-btn" id="sendBtn" onclick="send()">➤</button>
            </div>
        </div>
        <div class="powered-by">Heuchelberger Warte · Test-Version</div>
    </div>

    <script>
        const userId = 'mobile_' + Math.random().toString(36).substr(2, 9);
        const messages = document.getElementById('messages');
        const input = document.getElementById('input');
        const sendBtn = document.getElementById('sendBtn');

        input.addEventListener('keypress', e => {
            if (e.key === 'Enter') send();
        });

        async function send(text) {
            const msg = text || input.value.trim();
            if (!msg) return;

            addMsg(msg, 'user');
            input.value = '';
            sendBtn.disabled = true;

            const typing = showTyping();

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: msg, user_id: userId})
                });
                const data = await res.json();
                typing.remove();
                addMsg(data.response, 'bot');
            } catch(e) {
                typing.remove();
                addMsg('Verbindungsfehler - bitte nochmal versuchen', 'bot');
            }

            sendBtn.disabled = false;
            input.focus();
        }

        function addMsg(text, type) {
            const div = document.createElement('div');
            div.className = 'message ' + type;
            const linked = text.replace(/(https?:\\/\\/[^\\s]+)/g, '<a href="$1" target="_blank">$1</a>');
            const time = new Date().toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit'});
            div.innerHTML = linked + '<span class="time">' + time + '</span>';
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
        }

        function showTyping() {
            const div = document.createElement('div');
            div.className = 'typing';
            div.innerHTML = '<span></span><span></span><span></span>';
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
            return div;
        }
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
