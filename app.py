import streamlit as st
import anthropic

MODEL = "claude-sonnet-5-5"
BETAS = ["code-execution-2025-08-25", "skills-2025-10-02", "files-api-2025-04-14"]
SKILLS = [{"type": "anthropic", "skill_id": s, "version": "latest"} for s in ("xlsx", "docx", "pptx", "pdf")]
SYSTEM = (
    "Tu es un assistant personnel. Réponds toujours en français, de façon claire et soignée. "
    "Quand on te demande un fichier (Excel, Word, PowerPoint, PDF, CSV), crée-le avec l'outil "
    "d'exécution de code et enregistre-le dans le répertoire de travail courant."
)

st.set_page_config(page_title="Mon Claude", page_icon="💬")

# ---- Mot de passe ----
if not st.session_state.get("ok"):
    pwd = st.text_input("Mot de passe", type="password")
    if pwd:
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state.ok = True
            st.rerun()
        else:
            st.error("Mot de passe incorrect")
    st.stop()

client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

ss = st.session_state
ss.setdefault("api_messages", [])   # historique envoyé à l'API
ss.setdefault("display", [])        # historique affiché
ss.setdefault("container_id", None)
ss.setdefault("uploader_n", 0)


def find_file_ids(obj, found=None):
    """Cherche récursivement tous les file_id dans la réponse."""
    if found is None:
        found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "file_id" and isinstance(v, str) and v not in found:
                found.append(v)
            else:
                find_file_ids(v, found)
    elif isinstance(obj, list):
        for i in obj:
            find_file_ids(i, found)
    return found


def ask_claude(user_blocks):
    ss.api_messages.append({"role": "user", "content": user_blocks})
    text_parts, file_ids = [], []
    while True:
        container = {"skills": SKILLS}
        if ss.container_id:
            container["id"] = ss.container_id
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM,
            betas=BETAS,
            container=container,
            tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
            messages=ss.api_messages,
        )
        if resp.container:
            ss.container_id = resp.container.id
        ss.api_messages.append({"role": "assistant", "content": resp.content})
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            file_ids += [f for f in find_file_ids(block.model_dump()) if f not in file_ids]
        if resp.stop_reason == "pause_turn":
            continue
        break
    files = []
    for fid in file_ids:
        try:
            meta = client.beta.files.retrieve_metadata(fid)
            data = client.beta.files.download(fid).read()
            files.append({"name": meta.filename, "data": data})
        except Exception:
            pass  # fichiers d'entrée ou non téléchargeables
    return "\n\n".join(text_parts), files


# ---- Barre latérale ----
with st.sidebar:
    if st.button("🗑️ Nouvelle conversation"):
        for k in ("api_messages", "display", "container_id"):
            ss.pop(k, None)
        ss.uploader_n += 1
        st.rerun()
    uploads = st.file_uploader(
        "Joindre des fichiers", accept_multiple_files=True, key=f"up{ss.uploader_n}"
    )

st.title("💬 Mon Claude")

for i, m in enumerate(ss.display):
    with st.chat_message(m["role"]):
        st.markdown(m["text"])
        for j, f in enumerate(m.get("files", [])):
            st.download_button(f"⬇️ {f['name']}", f["data"], file_name=f["name"], key=f"d{i}_{j}")

prompt = st.chat_input("Écris ton message…")
if prompt:
    blocks = []
    for up in uploads or []:
        meta = client.beta.files.upload(file=(up.name, up.getvalue(), up.type or "application/octet-stream"))
        blocks.append({"type": "container_upload", "file_id": meta.id})
    blocks.append({"type": "text", "text": prompt})

    note = "".join(f"\n📎 {u.name}" for u in uploads or [])
    ss.display.append({"role": "user", "text": prompt + note})
    with st.chat_message("user"):
        st.markdown(prompt + note)
    with st.chat_message("assistant"):
        with st.spinner("Claude réfléchit…"):
            try:
                text, files = ask_claude(blocks)
            except Exception as e:
                text, files = f"⚠️ Erreur : {e}", []
        st.markdown(text)
    ss.display.append({"role": "assistant", "text": text, "files": files})
    ss.uploader_n += 1
    st.rerun()
