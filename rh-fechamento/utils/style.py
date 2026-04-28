"""
utils/style.py
Design system InChurch — Premium Brand Dark Mode.
"""
import streamlit as st

_FONTS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
"""

_CSS = """
<style>
:root {
  --bg-main:    #000000;
  --bg-card:    #121212;
  --bg-hover:   #1E1E1E;
  --border:     #292929;
  --border-hi:  #4c4c4c;
  --accent-1:   #6eda2c;
  --accent-2:   #57d124;
  --text-main:  #ffffff;
  --text-muted: #a0a0a0;
  --font-base:  'Outfit', sans-serif;
}

html, body, [class*="css"], .stApp, button, input, select, textarea {
  font-family: var(--font-base) !important;
}

.stApp { background: var(--bg-main) !important; }
section[data-testid="stSidebar"] { background: var(--bg-card) !important; border-right: 1px solid var(--border); }

h1 {
  font-size: 2rem !important;
  font-weight: 700 !important;
  color: var(--text-main) !important;
  margin-bottom: 4px !important;
  letter-spacing: -0.02em;
}
h1 span { color: var(--accent-1) !important; }

h2, h3 {
  font-family: var(--font-base) !important;
  font-size: 1.1rem !important;
  font-weight: 600 !important;
  color: var(--text-main) !important;
  border-bottom: 1px solid var(--border);
  border-left: 3px solid var(--accent-1);
  padding: 0 0 10px 12px !important;
  margin: 18px 0 16px 0 !important;
}

div[data-baseweb="select"] > div {
  background: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
  min-height: 44px !important;
  color: var(--text-main) !important;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
div[data-baseweb="select"] > div:hover {
  border-color: var(--accent-1) !important;
  box-shadow: 0 4px 12px rgba(110, 218, 44, 0.1) !important;
}

/* Botões de status customizados */
.status-btn-row {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}
.status-btn {
  flex: 1;
  padding: 14px 0;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-main);
  font-family: var(--font-base);
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: center;
}
.status-btn:hover { border-color: var(--accent-1); background: var(--bg-hover); }

hr { border-color: var(--border) !important; margin: 20px 0 !important; }

::-webkit-scrollbar { width: 7px; height: 7px; }
::-webkit-scrollbar-track { background: var(--bg-main); }
::-webkit-scrollbar-thumb { background: #4c4c4c; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #6c6c6c; }

div[data-testid="stAlert"] {
  background: var(--bg-card) !important;
  border-radius: 10px !important;
  border: 1px solid var(--border) !important;
}

div[data-testid="stAppViewBlockContainer"] { padding-top: 1.5rem !important; }

/* Card container */
.rh-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 28px 28px 24px;
  margin-top: 16px;
}
</style>
"""

_JS = """
<script>
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('svg title').forEach(el => el.remove());
});
</script>
"""


def inject_css() -> None:
    st.markdown(_FONTS, unsafe_allow_html=True)
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(_JS, unsafe_allow_html=True)
