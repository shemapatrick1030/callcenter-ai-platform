import streamlit as st

st.set_page_config(page_title="My Practice App", page_icon="🎓")

st.title("Streamlit Practice")

# Sidebar
with st.sidebar:
    st.header("Controls")
    name = st.text_input("Your name")
    color = st.selectbox("Favorite color", ["Red", "Blue", "Green"])

# Main area
st.subheader(f"Hello, {name}!")

if st.button("Click me"):
    st.balloons()
    st.success(f"{name}, your favorite color is {color}!")

# Two columns
col1, col2 = st.columns(2)
with col1:
    st.metric("Temperature", "72°F")
with col2:
    st.metric("Humidity", "45%")

# Expander
with st.expander("More info"):
    st.write("This is hidden until you click.")