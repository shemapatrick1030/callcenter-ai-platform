import sqlite3
import streamlit as st
from datetime import datetime
from groq import Groq
import asyncio
import tempfile
import os

# ============================================
# PAGE CONFIG
# ============================================
st.set_page_config(
    page_title="CallCenter AI Platform",
    page_icon="🤖",
    layout="wide"
)

# ============================================
# VOICE FUNCTIONS
# ============================================
def transcribe_audio_bytes(audio_bytes, api_key):
    """Convert recorded audio bytes to text using Groq Whisper"""
    client = Groq(api_key=api_key)
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    
    with open(tmp_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=("audio.wav", f.read()),
            response_format="text"
        )
    
    os.unlink(tmp_path)
    return transcription

def transcribe_audio(audio_bytes, api_key):
    """Convert recorded audio to text using Groq Whisper"""
    client = Groq(api_key=api_key)
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes.getvalue())
        tmp_path = tmp.name
    
    with open(tmp_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=("audio.wav", f.read()),
            response_format="text"
        )
    
    os.unlink(tmp_path)
    return transcription

def text_to_speech(text, voice="en-US-JennyNeural"):
    """Convert text to speech using Edge TTS (free)"""
    import edge_tts
    
    output_file = "response.mp3"
    
    async def _speak():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
    
    asyncio.run(_speak())
    return output_file

# ============================================
# DATABASE SETUP
# ============================================
def get_db():
    conn = sqlite3.connect("callcenter_web.db")
    return conn

def setup_database():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            industry TEXT DEFAULT 'general',
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            topic TEXT,
            content TEXT,
            source TEXT DEFAULT 'manual',
            created_at TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            question TEXT,
            answer TEXT,
            created_at TEXT
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM tenants")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO tenants (company_name, email, password, industry, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Acme Corp", "admin@acme.com", "password123", "retail", datetime.now().isoformat())
        )
        tenant_id = cursor.lastrowid
        
        knowledge = [
            ("Return Policy", "30-day returns. Original packaging required. Refunds in 5-7 business days."),
            ("Shipping", "Free shipping over $50. Standard 3-5 days. Express 1-2 days ($12.99)."),
            ("Business Hours", "Mon-Fri 8AM-8PM. Sat 9AM-5PM. Sun closed."),
        ]
        for topic, content in knowledge:
            cursor.execute(
                "INSERT INTO knowledge_base (tenant_id, topic, content, source, created_at) VALUES (?, ?, ?, 'manual', ?)",
                (tenant_id, topic, content, datetime.now().isoformat())
            )
    
    conn.commit()
    return conn

# ============================================
# AI FUNCTION
# ============================================
def ask_ai(question, knowledge_base, company_name, chat_history=None):
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    
    system_message = (
        f"You are Emily, a friendly and helpful customer support agent for {company_name}. "
        "You have a warm, professional personality.\n\n"
        "RULES FOR ANSWERING:\n"
        "1. If the question is about company policies, products, or services: "
        "Answer using ONLY the knowledge base below. If the info isn't there, "
        "say: 'I don't have that information available yet, but I can connect you with a human agent who can help.'\n\n"
        "2. If the question is casual small talk (like 'how are you?', 'what's your name?', "
        "'are you a robot?'): Respond naturally and warmly. Introduce yourself as Emily, "
        f"the virtual assistant for {company_name}. You can be friendly and conversational.\n\n"
        "3. If someone is frustrated or emotional: Show empathy first ('I understand that must be frustrating...'), "
        "then help them with their issue.\n\n"
        "4. NEVER make up information about company policies. But you CAN be warm, empathetic, "
        "and conversational in how you deliver information.\n\n"
        "5. Ask the name of the customer first and remember it during the whole conversation.\n\n"
        "6. You have to keep remembering the conversations within a session and use them to make sense and be more natural.\n\n"
        f"KNOWLEDGE BASE:\n{knowledge_base}"
    )
    
    messages = [{"role": "system", "content": system_message}]
    
    if chat_history:
        for msg in chat_history:
            messages.append({"role": msg["role"], "content": msg["content"]})
    
    if not chat_history:
        messages.append({"role": "user", "content": question})
    
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=1.0
    )
    return response.choices[0].message.content

# ============================================
# KNOWLEDGE FUNCTIONS
# ============================================
def get_knowledge(conn, tenant_id):
    cursor = conn.cursor()
    cursor.execute("SELECT id, topic, content, source FROM knowledge_base WHERE tenant_id = ?", (tenant_id,))
    return cursor.fetchall()

def get_knowledge_text(conn, tenant_id):
    rows = get_knowledge(conn, tenant_id)
    text = ""
    for _, topic, content, _ in rows:
        text += f"\n{topic}:\n{content}\n"
    return text

def add_knowledge(conn, tenant_id, topic, content, source="manual"):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO knowledge_base (tenant_id, topic, content, source, created_at) VALUES (?, ?, ?, ?, ?)",
        (tenant_id, topic, content, source, datetime.now().isoformat())
    )
    conn.commit()

def delete_knowledge(conn, knowledge_id):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM knowledge_base WHERE id = ?", (knowledge_id,))
    conn.commit()

# ============================================
# LOGIN / SESSION STATE
# ============================================
def login(email, password):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, company_name FROM tenants WHERE email = ? AND password = ?", (email, password))
    user = cursor.fetchone()
    conn.close()
    return user

def init_session():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.tenant_id = None
        st.session_state.company_name = None

# ============================================
# MAIN APP
# ============================================
def main():
    init_session()
    setup_database()
    
    # ============================================
    # SIDEBAR
    # ============================================
    with st.sidebar:
        st.title("🤖 CallCenter AI")
        
        if st.session_state.logged_in:
            st.success(f"✅ Logged in as **{st.session_state.company_name}**")
            
            st.markdown("---")
            st.subheader("📊 Quick Stats")
            
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM conversations WHERE tenant_id = ?", (st.session_state.tenant_id,))
            conv_count = cursor.fetchone()[0]
            st.metric("Total Conversations", conv_count)
            
            cursor.execute("SELECT COUNT(*) FROM knowledge_base WHERE tenant_id = ?", (st.session_state.tenant_id,))
            kb_count = cursor.fetchone()[0]
            st.metric("Knowledge Items", kb_count)
            
            conn.close()
            
            st.markdown("---")
            if st.button("🚪 Logout", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.tenant_id = None
                st.session_state.company_name = None
                st.rerun()
        else:
            st.info("👈 Log in to access your AI dashboard")
    
    # ============================================
    # MAIN CONTENT AREA
    # ============================================
    
    if not st.session_state.logged_in:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🔐 Login")
            st.markdown("Access your AI call center dashboard")
            
            email = st.text_input("Email", placeholder="admin@acme.com")
            password = st.text_input("Password", type="password", placeholder="password123")
            
            if st.button("Login", use_container_width=True, type="primary"):
                user = login(email, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.tenant_id = user[0]
                    st.session_state.company_name = user[1]
                    st.rerun()
                else:
                    st.error("Invalid email or password")
            
            st.markdown("---")
            st.caption("Demo: admin@acme.com / password123")
    
    else:
        st.title(f"🏢 {st.session_state.company_name} Dashboard")
        
        tab1, tab2, tab3, tab4 = st.tabs(["💬 Test AI", "📚 Knowledge Base", "📜 History", "🎙️ Voice Test"])
        
        # ============================================
        # TAB 1: TEST AI
        # ============================================
        with tab1:
            st.subheader("Test Your AI Agent")
            st.markdown("Type customer questions below to see how your AI responds.")
            
            if "chat_history" not in st.session_state:
                st.session_state.chat_history = []
            
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
            
            if question := st.chat_input("Type a customer question..."):
                st.session_state.chat_history.append({"role": "user", "content": question})
                
                conn = get_db()
                knowledge = get_knowledge_text(conn, st.session_state.tenant_id)
                
                if knowledge:
                    answer = ask_ai(question, knowledge, st.session_state.company_name, chat_history=st.session_state.chat_history)
                else:
                    answer = "⚠️ No knowledge base configured. Please add some information in the Knowledge Base tab."
                
                st.session_state.chat_history.append({"role": "assistant", "content": answer})
                
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO conversations (tenant_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
                    (st.session_state.tenant_id, question, answer, datetime.now().isoformat())
                )
                conn.commit()
                conn.close()
                
                if "don't have that information" in answer.lower() or "connect you with a human" in answer.lower():
                    st.session_state.last_unanswered = question
                
                st.rerun()
            
            if "last_unanswered" in st.session_state and st.session_state.last_unanswered:
                st.markdown("---")
                st.warning(f"⚠️ The AI couldn't answer: **'{st.session_state.last_unanswered}'**")
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    new_answer = st.text_input("What should the AI have said?", key="teach_input")
                with col2:
                    if st.button("📝 Teach AI", use_container_width=True) and new_answer:
                        conn = get_db()
                        add_knowledge(
                            conn, 
                            st.session_state.tenant_id, 
                            f"Q: {st.session_state.last_unanswered[:50]}", 
                            new_answer,
                            source="learned_from_chat"
                        )
                        conn.close()
                        st.success("✅ Knowledge added!")
                        del st.session_state.last_unanswered
                        st.rerun()
            
            if st.button("🗑️ Clear Chat"):
                st.session_state.chat_history = []
                st.rerun()
        
        # ============================================
        # TAB 2: KNOWLEDGE BASE
        # ============================================
        with tab2:
            st.subheader("Manage Knowledge Base")
            st.markdown("This is what your AI uses to answer customer questions.")
            
            with st.expander("➕ Add New Knowledge"):
                topic = st.text_input("Topic", placeholder="e.g., Return Policy")
                content = st.text_area("Content", placeholder="e.g., Returns accepted within 30 days...")
                if st.button("Add Knowledge"):
                    if topic and content:
                        conn = get_db()
                        add_knowledge(conn, st.session_state.tenant_id, topic, content)
                        conn.close()
                        st.success(f"✅ '{topic}' added!")
                        st.rerun()
                    else:
                        st.warning("Please fill in both fields.")
            
            st.subheader("Current Knowledge Items")
            conn = get_db()
            items = get_knowledge(conn, st.session_state.tenant_id)
            conn.close()
            
            if items:
                for item_id, topic, content, source in items:
                    with st.container(border=True):
                        col1, col2 = st.columns([4, 1])
                        with col1:
                            st.markdown(f"**{topic}**")
                            st.caption(content)
                            st.caption(f"Source: {source}")
                        with col2:
                            if st.button("🗑️", key=f"del_{item_id}"):
                                conn = get_db()
                                delete_knowledge(conn, item_id)
                                conn.close()
                                st.rerun()
            else:
                st.info("No knowledge items yet. Add your first one above!")
        
        # ============================================
        # TAB 3: HISTORY
        # ============================================
        with tab3:
            st.subheader("Conversation History")
            
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT question, answer, created_at FROM conversations WHERE tenant_id = ? ORDER BY id DESC LIMIT 20",
                (st.session_state.tenant_id,)
            )
            conversations = cursor.fetchall()
            conn.close()
            
            if conversations:
                for question, answer, timestamp in conversations:
                    with st.container(border=True):
                        st.chat_message("user").write(question)
                        st.chat_message("assistant").write(answer)
                        st.caption(f"📅 {timestamp[:16]}")
            else:
                st.info("No conversations yet. Test your AI in the 'Test AI' tab!")
        
        # ============================================
        # TAB 4: VOICE TEST
        # ============================================
        with tab4:
            from streamlit_mic_recorder import mic_recorder
            
            st.subheader("🎙️ Voice Test")
            st.markdown("Record your question and Emily will respond with her voice.")
            
            api_key = st.secrets["GROQ_API_KEY"]
            
            if "voice_history" not in st.session_state:
                st.session_state.voice_history = []
            
            # Record audio
            audio = mic_recorder(
                start_prompt="🎤 Click to Start Recording",
                stop_prompt="⏹️ Stop Recording",
                format="wav",
                key="voice_recorder"
            )
            
            if audio and audio.get("bytes"):
                audio_bytes = audio["bytes"]
                st.audio(audio_bytes, format="audio/wav")
                
                with st.spinner("🎤 Transcribing your voice..."):
                    question = transcribe_audio_bytes(audio_bytes, api_key)
                
                st.success(f"You said: **{question}**")
                
                with st.spinner("🧠 Emily is thinking..."):
                    conn = get_db()
                    knowledge = get_knowledge_text(conn, st.session_state.tenant_id)
                    
                    voice_history = []
                    for msg in st.session_state.voice_history:
                        voice_history.append({"role": msg["role"], "content": msg["content"]})
                    
                    answer = ask_ai(
                        question,
                        knowledge,
                        st.session_state.company_name,
                        chat_history=voice_history
                    )
                    conn.close()
                
                st.info(f"Emily says: **{answer}**")
                
                with st.spinner("🔊 Generating voice response..."):
                    audio_file = text_to_speech(answer)
                
                st.audio(audio_file, autoplay=True)
                
                st.session_state.voice_history.append({"role": "user", "content": question})
                st.session_state.voice_history.append({"role": "assistant", "content": answer})
                
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO conversations (tenant_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
                    (st.session_state.tenant_id, question, answer, datetime.now().isoformat())
                )
                conn.commit()
                conn.close()
            
            if st.session_state.voice_history:
                st.markdown("---")
                st.subheader("📜 This Voice Session")
                for msg in st.session_state.voice_history:
                    with st.chat_message(msg["role"]):
                        st.write(msg["content"])
                
                if st.button("🗑️ Clear Voice History"):
                    st.session_state.voice_history = []
                    st.rerun()

if __name__ == "__main__":
    main()