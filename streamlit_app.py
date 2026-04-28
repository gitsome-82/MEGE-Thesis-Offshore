from pathlib import Path
import runpy

# Stable root entrypoint for Streamlit Cloud deployment.
TARGET_APP = Path(__file__).resolve().parent / "3. system model" / "app" / "streamlit_app.py"
runpy.run_path(str(TARGET_APP), run_name="__main__")
