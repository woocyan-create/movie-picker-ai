"""Generate standalone architecture and flow JPGs (Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "docs"
OUT.mkdir(exist_ok=True)
try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
    TITLE = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
except OSError:
    FONT = ImageFont.load_default(size=22)
    TITLE = ImageFont.load_default(size=34)


def canvas(title):
    im = Image.new("RGB", (1440, 880), "#101014")
    draw = ImageDraw.Draw(im)
    draw.text((60, 35), title, fill="#d6c6ff", font=TITLE)
    return im, draw


def box(draw, xy, text):
    draw.rounded_rectangle(xy, 18, fill="#252130", outline="#9580bf", width=2)
    center = ((xy[0] + xy[2]) / 2, (xy[1] + xy[3]) / 2)
    draw.multiline_text(center, text, fill="#f2edf9", font=FONT, anchor="mm", align="center", spacing=10)


def arrow(draw, a, b):
    draw.line([a, b], fill="#bd9bea", width=4)
    x, y = b
    if a[0] == b[0]:
        draw.polygon([(x, y), (x - 8, y - 12), (x + 8, y - 12)], fill="#bd9bea")
    else:
        draw.polygon([(x, y), (x - 12, y - 8), (x - 12, y + 8)], fill="#bd9bea")


im, d = canvas("MOVIE PICKER / SYSTEM ARCHITECTURE")
box(d, (60, 140, 330, 270), "Streamlit\nChat + Movie Cards")
box(d, (420, 140, 700, 270), "FastAPI\n/chat /health /feedback")
box(d, (820, 140, 1370, 270), "LangGraph + SQLite Memory\nEmotion -> ReAct Retrieval -> Curator")
arrow(d, (330, 205), (420, 205))
arrow(d, (700, 205), (820, 205))
box(d, (70, 440, 380, 590), "SQLite\nFeedback + Disk Memory")
box(d, (460, 440, 780, 590), "Official IMDb TSVs\nClean + Join Ratings\nSQLite Movie Search")
box(d, (840, 440, 1130, 590), "Evidence RAG\nChunks + Embeddings\nChroma Index")
box(d, (1170, 440, 1390, 590), "ReAct Tools\nSearch / Retrieve\nInspect Metadata")
arrow(d, (560, 270), (560, 440))
arrow(d, (985, 270), (985, 440))
arrow(d, (1280, 270), (1280, 440))
d.line([(420, 260), (225, 360), (225, 440)], fill="#bd9bea", width=3)
d.text((70, 690), "Structured outputs: Pydantic validation / Session UUID isolation / Strict runtime + genre filters", fill="#c4becf", font=FONT)
d.text((70, 740), "Live: LLM Function Calling + semantic embeddings. Demo: rule planner + lexical hash vectors.", fill="#c4becf", font=FONT)
im.save(OUT / "architecture.jpg", quality=95)

im, d = canvas("MOVIE PICKER / RECOMMENDATION FLOW")
items = [
    ((80, 150, 480, 260), "1. User message + constraints"),
    ((80, 330, 480, 460), "2. EmotionAnalyzerAgent\nFew-shot + structured preferences"),
    ((660, 330, 1310, 460), "3. MovieRetrieverAgent\nFunction Calling <-> Tools / Observations"),
    ((660, 560, 1310, 690), "4. CuratorAgent\nIMDb candidates + verified evidence chunks"),
    ((80, 560, 480, 690), "Clarification question\nwhen preferences are missing"),
]
for xy, label in items:
    box(d, xy, label)
arrow(d, (280, 260), (280, 330))
arrow(d, (480, 395), (660, 395))
arrow(d, (280, 460), (280, 560))
arrow(d, (985, 460), (985, 560))
d.text((80, 760), "Response -> FastAPI -> Streamlit cards -> User feedback -> SQLite", fill="#c4becf", font=FONT)
im.save(OUT / "flow.jpg", quality=95)
