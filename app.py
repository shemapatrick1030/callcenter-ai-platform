import sqlite3
import streamlit as st
from datetime import datetime
from groq import Groq
import asyncio
import tempfile
import os
from streamlit_mic_recorder import mic_recorder

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
    db_path = os.path.join(os.path.dirname(__file__), "callcenter_web.db")
    conn = sqlite3.connect(db_path)
    return conn

def setup_database():
    conn = get_db()
    cursor = conn.cursor()
    
    # Drop old tables to rebuild fresh (REMOVE THESE 4 LINES AFTER FIRST SUCCESSFUL DEPLOY)
    cursor.execute("DROP TABLE IF EXISTS conversations")
    cursor.execute("DROP TABLE IF EXISTS knowledge_base")
    cursor.execute("DROP TABLE IF EXISTS signup_requests")
    cursor.execute("DROP TABLE IF EXISTS tenants")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT DEFAULT '',
            industry TEXT DEFAULT 'general',
            plan TEXT DEFAULT 'trial',
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signup_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            industry TEXT DEFAULT 'general',
            plan TEXT DEFAULT 'basic',
            message TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
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
        # Create admin account
        cursor.execute(
            "INSERT INTO tenants (company_name, email, password, industry, plan, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("Admin", "admin@callcenter.ai", "admin123", "admin", "enterprise", datetime.now().isoformat())
        )
        
        # Create demo client
        cursor.execute(
            "INSERT INTO tenants (company_name, email, password, phone, industry, plan, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("CallCenter AI", "admin@callcenter.com", "password123", "0798507184", "rental", "trial", datetime.now().isoformat())
        )
        tenant_id = cursor.lastrowid
        
        knowledge = [
            ("Renting Policy", "Rent our AI frontdesk assistant and callcenter handler for 30 days and the price varies according to the plan you choose. Visit our website for more."),
            ("Payment Plan", "You pay first and we provide you with the access key to use our AI which lasts for 30 days. Upgrade before end of plan for discounts."),
            ("Privacy Policy", "No one can access your data, not even our admins because your key is private and fully encrypted. However, should you use our product against the laws, you may face blocking and other punishments. You can read more about this in privacy policy through our website or in the contract when you have paid for the plan."),
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
        "7. You are allowed to be a bit more serious when someone is clearly and intentionally messing with you.\n\n"
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
    cursor.execute("SELECT id, company_name, industry FROM tenants WHERE email = ? AND password = ? AND is_active = 1", (email, password))
    user = cursor.fetchone()
    conn.close()
    if user:
        return {"id": user[0], "company_name": user[1], "is_admin": user[2] == "admin"}
    return None

def init_session():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.tenant_id = None
        st.session_state.company_name = None
        st.session_state.is_admin = False

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
            
            if not st.session_state.is_admin:
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
                for key in ["logged_in", "tenant_id", "company_name", "is_admin", "chat_history", "voice_history", "show_signup", "selected_plan", "last_unanswered"]:
                    if key in st.session_state:
                        del st.session_state[key]
                init_session()
                st.rerun()
        else:
            st.info("👈 Log in to access your AI dashboard")
    
    # ============================================
    # MAIN CONTENT AREA
    # ============================================
    
    if not st.session_state.logged_in:
        # PUBLIC LANDING PAGE
        st.title("🤖 AI Call Center Agents for Your Business")
        st.markdown("### Never miss a customer call again. Let AI handle support 24/7.")
        
        # Hero metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("⏰", "24/7 Availability")
        with col2:
            st.metric("💰", "90% Cost Savings")
        with col3:
            st.metric("🌍", "English + Kinyarwanda Soon")
        
        st.markdown("---")
        
        # Features
        st.subheader("✨ What You Get")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("**🎓 Train Your AI**\nUpload your FAQs, policies, and product info. Your AI learns instantly.")
        with col2:
            st.markdown("**📞 Voice & Chat**\nCustomers can talk or type. AI responds naturally.")
        with col3:
            st.markdown("**📊 Analytics**\nSee every conversation. Know what customers ask most.")
        
        st.markdown("---")
        
        # Pricing
        st.subheader("💎 Pricing Plans")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("### Starter\n**$99/month**\n- Up to 500 calls/month\n- 1 AI agent\n- Email support\n- English only")
            if st.button("Get Started", key="starter"):
                st.session_state.show_signup = True
                st.session_state.selected_plan = "starter"
        
        with col2:
            st.markdown("### Business\n**$199/month**\n- Up to 2,000 calls/month\n- 3 AI agents\n- Priority support\n- English + Analytics")
            if st.button("Get Started", key="business"):
                st.session_state.show_signup = True
                st.session_state.selected_plan = "business"
        
        with col3:
            st.markdown("### Enterprise\n**Custom**\n- Unlimited calls\n- Unlimited agents\n- Dedicated support\n- Kinyarwanda (coming)")
            if st.button("Contact Us", key="enterprise"):
                st.session_state.show_signup = True
                st.session_state.selected_plan = "enterprise"
        
        st.markdown("---")
        
        # Signup Form
        if st.session_state.get("show_signup"):
            st.subheader(f"📝 Sign Up - {st.session_state.selected_plan.title()} Plan")
            
            col1, col2 = st.columns(2)
            with col1:
                company_name = st.text_input("Company Name*")
                contact_name = st.text_input("Your Name*")
            with col2:
                email = st.text_input("Email*")
                phone = st.text_input("Phone*")
            
            industry = st.selectbox("Industry", ["Retail", "Banking", "Insurance", "Healthcare", "Technology", "Hospitality", "Other"])
            message = st.text_area("Tell us about your needs (optional)")
            
            if st.button("Submit Request", type="primary"):
                if company_name and contact_name and email and phone:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO signup_requests (company_name, contact_name, email, phone, industry, plan, message, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                        (company_name, contact_name, email, phone, industry, st.session_state.selected_plan, message, datetime.now().isoformat())
                    )
                    conn.commit()
                    conn.close()
                    st.success("✅ Request submitted! We'll review and get back to you within 24 hours.")
                    st.session_state.show_signup = False
                    st.rerun()
                else:
                    st.error("Please fill in all required fields (*)")
        
        # Login section
        st.markdown("---")
        st.subheader("🔐 Already a client?")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            email_login = st.text_input("Email", key="login_email", placeholder="admin@callcenter.com")
            password_login = st.text_input("Password", type="password", key="login_password", placeholder="password123")
            if st.button("Login", use_container_width=True):
                user = login(email_login, password_login)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.tenant_id = user["id"]
                    st.session_state.company_name = user["company_name"]
                    st.session_state.is_admin = user["is_admin"]
                    st.rerun()
                else:
                    st.error("Invalid credentials")
        
        st.caption("Demo: admin@callcenter.com / password123 | Admin: admin@callcenter.ai / admin123")
    
    elif st.session_state.is_admin:
        # ADMIN DASHBOARD
        st.title("🔐 Admin Dashboard")
        
        tab1, tab2, tab3 = st.tabs(["📋 Signup Requests", "🏢 Tenants", "📊 Analytics"])
        
        with tab1:
            st.subheader("Pending Signup Requests")
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM signup_requests WHERE status = 'pending' ORDER BY created_at DESC")
            requests = cursor.fetchall()
            
            if requests:
                for req in requests:
                    req_id, company, contact, email, phone, industry, plan, message, status, created = req
                    with st.container(border=True):
                        st.markdown(f"**{company}** | {industry} | Plan: {plan.title()}")
                        st.markdown(f"Contact: {contact} | {email} | {phone}")
                        if message:
                            st.caption(f"Message: {message}")
                        st.caption(f"Submitted: {created[:16]}")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button(f"✅ Approve", key=f"approve_{req_id}"):
                                import secrets
                                password = secrets.token_hex(8)
                                cursor.execute(
                                    "INSERT INTO tenants (company_name, email, password, phone, industry, plan, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                    (company, email, password, phone, industry, plan, datetime.now().isoformat())
                                )
                                cursor.execute("UPDATE signup_requests SET status = 'approved' WHERE id = ?", (req_id,))
                                conn.commit()
                                st.success(f"Approved! Temporary password: {password}")
                                st.rerun()
                        with col2:
                            if st.button(f"❌ Reject", key=f"reject_{req_id}"):
                                cursor.execute("UPDATE signup_requests SET status = 'rejected' WHERE id = ?", (req_id,))
                                conn.commit()
                                st.rerun()
            else:
                st.info("No pending requests.")
            conn.close()
        
        with tab2:
            st.subheader("All Tenants")
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, company_name, email, phone, industry, plan, is_active, created_at FROM tenants WHERE industry != 'admin'")
            tenants = cursor.fetchall()
            
            if tenants:
                for t in tenants:
                    t_id, name, email, phone, industry, plan, active, created = t
                    with st.container(border=True):
                        status = "🟢 Active" if active else "🔴 Inactive"
                        st.markdown(f"**{name}** | {industry} | {plan.title()} | {status}")
                        st.markdown(f"{email} | {phone} | Joined: {created[:10]}")
                        
                        if active:
                            if st.button(f"🔴 Suspend", key=f"suspend_{t_id}"):
                                cursor.execute("UPDATE tenants SET is_active = 0 WHERE id = ?", (t_id,))
                                conn.commit()
                                st.rerun()
                        else:
                            if st.button(f"🟢 Activate", key=f"activate_{t_id}"):
                                cursor.execute("UPDATE tenants SET is_active = 1 WHERE id = ?", (t_id,))
                                conn.commit()
                                st.rerun()
            else:
                st.info("No tenants yet.")
            conn.close()
        
        with tab3:
            st.subheader("Platform Analytics")
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM tenants WHERE industry != 'admin'")
            total_tenants = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM conversations")
            total_conversations = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM signup_requests WHERE status = 'pending'")
            pending = cursor.fetchone()[0]
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Clients", total_tenants)
            with col2:
                st.metric("Total Conversations", total_conversations)
            with col3:
                st.metric("Pending Requests", pending)
            
            conn.close()
    
    else:
        # CLIENT DASHBOARD
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
            
            if st.session_state.get("last_unanswered"):
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
            st.subheader("🎙️ Voice Test")
            st.markdown("Record your question and Emily will respond with her voice.")
            
            api_key = st.secrets["GROQ_API_KEY"]
            
            if "voice_history" not in st.session_state:
                st.session_state.voice_history = []
            
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
                    
                    voice_messages = []
                    for msg in st.session_state.voice_history:
                        voice_messages.append({"role": msg["role"], "content": msg["content"]})
                    voice_messages.append({"role": "user", "content": question})
                    
                    system_message = (
                        f"You are Emily, a friendly customer support agent for {st.session_state.company_name}. "
                        "Be warm and conversational. Remember what was said earlier in the conversation. "
                        "Answer using ONLY the knowledge base below. If you don't know, say you'll connect to a human agent.\n\n"
                        f"KNOWLEDGE BASE:\n{knowledge}"
                    )
                    
                    full_messages = [{"role": "system", "content": system_message}]
                    for msg in voice_messages:
                        full_messages.append(msg)
                    
                    client = Groq(api_key=api_key)
                    response = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=full_messages,
                        temperature=1.0
                    )
                    answer = response.choices[0].message.content
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