import streamlit as st
from datetime import datetime
from groq import Groq
import asyncio
import tempfile
import os
from supabase import create_client
from streamlit_mic_recorder import mic_recorder

st.set_page_config(page_title="CallCenter AI Platform", page_icon="🤖", layout="wide")

# ============================================
# SUPABASE SETUP
# ============================================
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def setup_database():
    """Create tables using Supabase SQL (runs once via REST)"""
    supabase = get_supabase()
    
    # Check if tenants table has data
    result = supabase.table("tenants").select("id").limit(1).execute()
    
    if len(result.data) == 0:
        # Insert admin
        supabase.table("tenants").insert({
            "company_name": "Admin",
            "email": "admin@callcenter.ai",
            "password": "admin123",
            "industry": "admin",
            "plan": "enterprise"
        }).execute()
        
        # Insert demo client
        supabase.table("tenants").insert({
            "company_name": "CallCenter AI",
            "email": "admin@callcenter.com",
            "password": "password123",
            "phone": "0798507184",
            "industry": "rental",
            "plan": "trial"
        }).execute()
        
        # Get demo client ID
        result = supabase.table("tenants").select("id").eq("email", "admin@callcenter.com").execute()
        tenant_id = result.data[0]["id"]
        
        # Insert knowledge
        knowledge = [
            {"tenant_id": tenant_id, "topic": "Renting Policy", "content": "Rent our AI frontdesk assistant and callcenter handler for 30 days. Price varies by plan. Visit our website for more.", "source": "manual"},
            {"tenant_id": tenant_id, "topic": "Payment Plan", "content": "You pay first and we provide you with the access key to use our AI which lasts for 30 days. Upgrade before end of plan for discounts.", "source": "manual"},
            {"tenant_id": tenant_id, "topic": "Privacy Policy", "content": "No one can access your data, not even our admins. Your key is private and fully encrypted. Misuse may result in blocking.", "source": "manual"},
        ]
        for item in knowledge:
            supabase.table("knowledge_base").insert(item).execute()

# ============================================
# VOICE FUNCTIONS
# ============================================
def transcribe_audio_bytes(audio_bytes, api_key):
    client = Groq(api_key=api_key)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    with open(tmp_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo", file=("audio.wav", f.read()), response_format="text"
        )
    os.unlink(tmp_path)
    return transcription

def text_to_speech(text, voice="en-US-JennyNeural"):
    import edge_tts
    output_file = "response.mp3"
    async def _speak():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
    asyncio.run(_speak())
    return output_file

# ============================================
# AI FUNCTION
# ============================================
def ask_ai(question, knowledge_base, company_name, chat_history=None):
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    system_message = (
        f"You are Emily, a friendly customer support agent for {company_name}. "
        "Be warm and professional. Answer using ONLY the knowledge base below. "
        "If you don't know, say you'll connect to a human agent.\n\n"
        f"KNOWLEDGE BASE:\n{knowledge_base}"
    )
    messages = [{"role": "system", "content": system_message}]
    if chat_history:
        for msg in chat_history:
            messages.append({"role": msg["role"], "content": msg["content"]})
    else:
        messages.append({"role": "user", "content": question})
    
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant", messages=messages, temperature=1.0
    )
    return response.choices[0].message.content

# ============================================
# DATABASE HELPERS
# ============================================
def login(email, password):
    supabase = get_supabase()
    result = supabase.table("tenants").select("*").eq("email", email).eq("password", password).eq("is_active", True).execute()
    if result.data:
        user = result.data[0]
        return {"id": user["id"], "company_name": user["company_name"], "is_admin": user["industry"] == "admin"}
    return None

def get_knowledge_text(tenant_id):
    supabase = get_supabase()
    result = supabase.table("knowledge_base").select("topic, content").eq("tenant_id", tenant_id).execute()
    text = ""
    for row in result.data:
        text += f"\n{row['topic']}:\n{row['content']}\n"
    return text

def get_knowledge_items(tenant_id):
    supabase = get_supabase()
    result = supabase.table("knowledge_base").select("*").eq("tenant_id", tenant_id).execute()
    return result.data

def add_knowledge(tenant_id, topic, content, source="manual"):
    supabase = get_supabase()
    supabase.table("knowledge_base").insert({
        "tenant_id": tenant_id, "topic": topic, "content": content, "source": source
    }).execute()

def delete_knowledge(knowledge_id):
    supabase = get_supabase()
    supabase.table("knowledge_base").delete().eq("id", knowledge_id).execute()

def save_conversation(tenant_id, question, answer):
    supabase = get_supabase()
    supabase.table("conversations").insert({
        "tenant_id": tenant_id, "question": question, "answer": answer
    }).execute()

def get_conversations(tenant_id, limit=20):
    supabase = get_supabase()
    result = supabase.table("conversations").select("*").eq("tenant_id", tenant_id).order("id", desc=True).limit(limit).execute()
    return result.data

def get_pending_requests():
    supabase = get_supabase()
    result = supabase.table("signup_requests").select("*").eq("status", "pending").order("created_at", desc=True).execute()
    return result.data

def get_all_tenants():
    supabase = get_supabase()
    result = supabase.table("tenants").select("*").neq("industry", "admin").order("created_at", desc=True).execute()
    return result.data

def get_analytics():
    supabase = get_supabase()
    tenants = supabase.table("tenants").select("id", count="exact").neq("industry", "admin").execute()
    convs = supabase.table("conversations").select("id", count="exact").execute()
    pending = supabase.table("signup_requests").select("id", count="exact").eq("status", "pending").execute()
    return tenants.count, convs.count, pending.count

# ============================================
# SESSION INIT
# ============================================
def init_session():
    defaults = {
        "logged_in": False, "tenant_id": None, "company_name": None, "is_admin": False,
        "chat_history": [], "voice_history": [], "show_signup": False, "selected_plan": "starter"
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

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
            st.success(f"✅ {st.session_state.company_name}")
            if not st.session_state.is_admin:
                convs = get_conversations(st.session_state.tenant_id, 1000)
                items = get_knowledge_items(st.session_state.tenant_id)
                st.metric("Conversations", len(convs))
                st.metric("Knowledge Items", len(items))
            if st.button("🚪 Logout", use_container_width=True):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                init_session()
                st.rerun()
        else:
            st.info("👈 Login to continue")
    
    # ============================================
    # LANDING PAGE
    # ============================================
    if not st.session_state.logged_in:
        st.title("🤖 AI Call Center Agents for Your Business")
        st.markdown("### Never miss a customer call again. 24/7 AI support.")
        
        c1, c2, c3 = st.columns(3)
        c1.metric("⏰", "24/7 Availability")
        c2.metric("💰", "90% Cost Savings")
        c3.metric("🌍", "English + Kinyarwanda Soon")
        
        st.markdown("---")
        st.subheader("💎 Pricing Plans")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            st.markdown("### Starter\n**$99/mo**\n500 calls/mo")
            if st.button("Get Started", key="starter"):
                st.session_state.show_signup = True
                st.session_state.selected_plan = "starter"
        with pc2:
            st.markdown("### Business\n**$199/mo**\n2000 calls/mo")
            if st.button("Get Started", key="business"):
                st.session_state.show_signup = True
                st.session_state.selected_plan = "business"
        with pc3:
            st.markdown("### Enterprise\n**Custom**\nUnlimited")
            if st.button("Contact Us", key="enterprise"):
                st.session_state.show_signup = True
                st.session_state.selected_plan = "enterprise"
        
        st.markdown("---")
        
        if st.session_state.show_signup:
            st.subheader(f"📝 Sign Up - {st.session_state.selected_plan.title()}")
            c1, c2 = st.columns(2)
            company_name = c1.text_input("Company Name*")
            contact_name = c2.text_input("Your Name*")
            email = c1.text_input("Email*")
            phone = c2.text_input("Phone*")
            industry = st.selectbox("Industry", ["Retail", "Banking", "Insurance", "Healthcare", "Technology", "Other"])
            message = st.text_area("Tell us about your needs")
            
            if st.button("Submit Request", type="primary"):
                if company_name and contact_name and email and phone:
                    supabase = get_supabase()
                    supabase.table("signup_requests").insert({
                        "company_name": company_name, "contact_name": contact_name,
                        "email": email, "phone": phone, "industry": industry,
                        "plan": st.session_state.selected_plan, "message": message
                    }).execute()
                    st.success("✅ Submitted! We'll get back to you within 24 hours.")
                    st.session_state.show_signup = False
                    st.rerun()
                else:
                    st.error("Fill all required fields.")
        
        st.markdown("---")
        st.subheader("🔐 Already a client?")
        email_login = st.text_input("Email", key="login_email", placeholder="admin@callcenter.com")
        password_login = st.text_input("Password", type="password", key="login_pass", placeholder="password123")
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
    
    # ============================================
    # ADMIN DASHBOARD
    # ============================================
    elif st.session_state.is_admin:
        st.title("🔐 Admin Dashboard")
        tab1, tab2, tab3 = st.tabs(["📋 Signup Requests", "🏢 Tenants", "📊 Analytics"])
        
        with tab1:
            st.subheader("Pending Requests")
            requests = get_pending_requests()
            if requests:
                for req in requests:
                    with st.container(border=True):
                        st.markdown(f"**{req['company_name']}** | {req['industry']} | {req['plan'].title()}")
                        st.markdown(f"{req['contact_name']} | {req['email']} | {req['phone']}")
                        st.caption(f"Submitted: {str(req['created_at'])[:16]}")
                        c1, c2 = st.columns(2)
                        if c1.button("✅ Approve", key=f"app_{req['id']}"):
                            import secrets
                            pw = secrets.token_hex(8)
                            supabase = get_supabase()
                            supabase.table("tenants").insert({
                                "company_name": req["company_name"], "email": req["email"],
                                "password": pw, "phone": req["phone"],
                                "industry": req["industry"], "plan": req["plan"]
                            }).execute()
                            supabase.table("signup_requests").update({"status": "approved"}).eq("id", req["id"]).execute()
                            st.success(f"Approved! Password: {pw}")
                            st.rerun()
                        if c2.button("❌ Reject", key=f"rej_{req['id']}"):
                            supabase = get_supabase()
                            supabase.table("signup_requests").update({"status": "rejected"}).eq("id", req["id"]).execute()
                            st.rerun()
            else:
                st.info("No pending requests.")
        
        with tab2:
            st.subheader("All Tenants")
            tenants = get_all_tenants()
            if tenants:
                for t in tenants:
                    with st.container(border=True):
                        s = "🟢 Active" if t["is_active"] else "🔴 Inactive"
                        st.markdown(f"**{t['company_name']}** | {t['industry']} | {t['plan'].title()} | {s}")
                        st.markdown(f"{t['email']} | {t.get('phone', 'N/A')}")
                        if t["is_active"]:
                            if st.button("🔴 Suspend", key=f"sus_{t['id']}"):
                                supabase = get_supabase()
                                supabase.table("tenants").update({"is_active": False}).eq("id", t["id"]).execute()
                                st.rerun()
                        else:
                            if st.button("🟢 Activate", key=f"act_{t['id']}"):
                                supabase = get_supabase()
                                supabase.table("tenants").update({"is_active": True}).eq("id", t["id"]).execute()
                                st.rerun()
            else:
                st.info("No tenants yet.")
        
        with tab3:
            total_tenants, total_convs, pending = get_analytics()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Clients", total_tenants)
            c2.metric("Total Conversations", total_convs)
            c3.metric("Pending Requests", pending)
    
    # ============================================
    # CLIENT DASHBOARD
    # ============================================
    else:
        st.title(f"🏢 {st.session_state.company_name} Dashboard")
        tab1, tab2, tab3, tab4 = st.tabs(["💬 Test AI", "📚 Knowledge Base", "📜 History", "🎙️ Voice Test"])
        
        with tab1:
            st.subheader("Test Your AI Agent")
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
            
            if question := st.chat_input("Type a customer question..."):
                st.session_state.chat_history.append({"role": "user", "content": question})
                knowledge = get_knowledge_text(st.session_state.tenant_id)
                answer = ask_ai(question, knowledge, st.session_state.company_name, chat_history=st.session_state.chat_history) if knowledge else "⚠️ No knowledge base. Add items in the Knowledge Base tab."
                st.session_state.chat_history.append({"role": "assistant", "content": answer})
                save_conversation(st.session_state.tenant_id, question, answer)
                st.rerun()
            
            if st.button("🗑️ Clear Chat"):
                st.session_state.chat_history = []
                st.rerun()
        
        with tab2:
            st.subheader("Manage Knowledge Base")
            with st.expander("➕ Add New Knowledge"):
                topic = st.text_input("Topic")
                content = st.text_area("Content")
                if st.button("Add Knowledge"):
                    if topic and content:
                        add_knowledge(st.session_state.tenant_id, topic, content)
                        st.success(f"✅ '{topic}' added!")
                        st.rerun()
                    else:
                        st.warning("Fill both fields.")
            
            st.subheader("Current Knowledge")
            items = get_knowledge_items(st.session_state.tenant_id)
            if items:
                for item in items:
                    with st.container(border=True):
                        st.markdown(f"**{item['topic']}**")
                        st.caption(item["content"])
                        if st.button("🗑️", key=f"del_{item['id']}"):
                            delete_knowledge(item["id"])
                            st.rerun()
            else:
                st.info("No items yet.")
        
        with tab3:
            st.subheader("Conversation History")
            convs = get_conversations(st.session_state.tenant_id)
            if convs:
                for c in reversed(convs):
                    with st.container(border=True):
                        st.chat_message("user").write(c["question"])
                        st.chat_message("assistant").write(c["answer"])
                        st.caption(f"📅 {str(c['created_at'])[:16]}")
            else:
                st.info("No conversations yet.")
        
        with tab4:
            st.subheader("🎙️ Voice Test")
            api_key = st.secrets["GROQ_API_KEY"]
            audio = mic_recorder(start_prompt="🎤 Start Recording", stop_prompt="⏹️ Stop", format="wav", key="voice_rec")
            
            if audio and audio.get("bytes"):
                audio_bytes = audio["bytes"]
                st.audio(audio_bytes, format="audio/wav")
                
                with st.spinner("🎤 Transcribing..."):
                    question = transcribe_audio_bytes(audio_bytes, api_key)
                st.success(f"You said: **{question}**")
                
                with st.spinner("🧠 Thinking..."):
                    knowledge = get_knowledge_text(st.session_state.tenant_id)
                    voice_messages = []
                    for msg in st.session_state.voice_history:
                        voice_messages.append({"role": msg["role"], "content": msg["content"]})
                    voice_messages.append({"role": "user", "content": question})
                    
                    system_message = (
                        f"You are Emily for {st.session_state.company_name}. "
                        "Be warm and conversational. Use the knowledge base.\n\n"
                        f"KNOWLEDGE BASE:\n{knowledge}"
                    )
                    full_messages = [{"role": "system", "content": system_message}] + voice_messages
                    
                    client = Groq(api_key=api_key)
                    response = client.chat.completions.create(
                        model="llama-3.1-8b-instant", messages=full_messages, temperature=1.0
                    )
                    answer = response.choices[0].message.content
                
                st.info(f"Emily: **{answer}**")
                
                with st.spinner("🔊 Generating voice..."):
                    audio_file = text_to_speech(answer)
                st.audio(audio_file, autoplay=True)
                
                st.session_state.voice_history.append({"role": "user", "content": question})
                st.session_state.voice_history.append({"role": "assistant", "content": answer})
                save_conversation(st.session_state.tenant_id, question, answer)
            
            if st.session_state.voice_history:
                st.markdown("---")
                for msg in st.session_state.voice_history:
                    with st.chat_message(msg["role"]):
                        st.write(msg["content"])
                if st.button("🗑️ Clear Voice History"):
                    st.session_state.voice_history = []
                    st.rerun()

if __name__ == "__main__":
    main()