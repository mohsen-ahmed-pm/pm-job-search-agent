"""
read_profile.py -- Load user profile documents.
In Modal: reads from /profile (Volume mount).
Locally: reads from Mohsen Profile/ folder at project root.
Supports .txt, .docx, and .pdf files.
"""

import os

# Modal Volume is mounted at /profile; local fallback is Mohsen Profile/ folder
PROFILE_DIR = (
    "/profile"
    if os.path.isdir("/profile") and any(
        f for f in os.listdir("/profile") if not f.startswith(".")
    )
    else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Mohsen Profile")
)


def _read_txt(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _read_docx(path):
    try:
        import docx
        doc = docx.Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise ImportError("python-docx is required to read .docx files.")


def _read_pdf(path):
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        return "\n".join(text_parts)
    except ImportError:
        raise ImportError("pdfplumber is required to read .pdf files.")


def load_profile():
    """
    Read all .txt, .docx, and .pdf files from the profile folder.
    Returns a single combined string. Raises ValueError if folder is empty or missing.
    """
    profile_dir = (
        "/profile"
        if os.path.isdir("/profile") and any(
            f for f in os.listdir("/profile") if not f.startswith(".")
        )
        else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Mohsen Profile")
    )

    if not os.path.isdir(profile_dir):
        raise ValueError(
            f"Profile folder not found: {profile_dir}\n"
            "Add your resume, TMAY, and experience docs to the profile folder."
        )

    readers = {".txt": _read_txt, ".docx": _read_docx, ".pdf": _read_pdf}
    sections = []

    for root, dirs, files in os.walk(profile_dir):
        for filename in sorted(files):
            if filename == "README.txt":
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in readers:
                continue
            filepath = os.path.join(root, filename)
            print(f"[read_profile] Loading: {filename}")
            text = readers[ext](filepath).strip()
            if text:
                sections.append(f"=== {filename} ===\n{text}")

    if not sections:
        raise ValueError(
            f"No profile documents found in: {profile_dir}\n"
            "Add your resume (.txt/.docx/.pdf), TMAY, and experience narratives."
        )

    combined = "\n\n".join(sections)
    print(f"[read_profile] Loaded {len(sections)} document(s), {len(combined):,} chars total.")
    return combined


if __name__ == "__main__":
    profile = load_profile()
    print("\n--- PROFILE PREVIEW (first 500 chars) ---")
    print(profile[:500])