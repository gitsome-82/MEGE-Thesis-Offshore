from pathlib import Path
import runpy


TARGET_APP = (
    Path(__file__).resolve().parent.parent
    / "2. generation and load, scaling"
    / "demo DE offshore gen vs load streamlit dash.py"
)

runpy.run_path(str(TARGET_APP), run_name="__main__")