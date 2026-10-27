"""Idempotent demo seed data: classes A/B, four demo accounts, one material."""
import os

from flask import current_app

from .db import db
from .models import Class, Material, User
from .security import hash_password
from .storage import write_bytes

DEMO_ACCOUNTS = [
    ("teacher_a", "teacher", "A班"),
    ("student_a", "student", "A班"),
    ("teacher_b", "teacher", "B班"),
    ("student_b", "student", "B班"),
]

# Minimal valid one-page PDF (text: "CampusClaw demo").
SAMPLE_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
    b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 58>>stream\nBT /F1 18 Tf 72 720 Td (CampusClaw demo) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 6\ntrailer<</Size 6/Root 1 0 R>>\n%%EOF\n"
)

# Class A: biology (markdown). Class B: Tang dynasty history (plain text).
BIO_MD = """# 高中生物·能量与代谢

## 光合作用
光合作用是绿色植物通过叶绿体，利用光能把二氧化碳和水转化成储存能量的有机物，并且释放氧气的过程。
光反应阶段发生在类囊体薄膜上，水在光下分解产生氧气，同时生成 ATP 和 NADPH。
暗反应阶段又称卡尔文循环，在叶绿体基质中进行，完成二氧化碳的固定和三碳糖的还原。

## 细胞呼吸
细胞呼吸是有机物在细胞内经过一系列氧化分解生成二氧化碳或其他产物、释放能量并合成 ATP 的过程。
有氧呼吸分为糖酵解、三羧酸循环和氧化磷酸化三个阶段，主要在线粒体中完成。
无氧呼吸不经过线粒体，在细胞质基质中把葡萄糖分解为乳酸或酒精，释放的能量较少。

## 遗传与进化
孟德尔通过豌豆杂交实验提出了基因的分离定律和自由组合定律。
基因是具有遗传效应的 DNA 片段，通过转录和翻译控制蛋白质的合成。
现代生物进化理论认为，自然选择决定生物进化的方向，种群基因频率的改变是进化的实质。
"""

HIST_TXT = """第一讲 唐朝的建立与兴盛
唐朝是中国历史上强盛的大一统王朝，定都长安，疆域辽阔，经济文化繁荣，对外交流频繁。
唐高祖李渊在隋末战乱中起兵，公元六一八年称帝建立唐朝，随后逐步统一全国。
唐太宗李世民即位后虚心纳谏、任用魏征房玄龄杜如晦等贤臣，开创了著名的贞观之治。

第二讲 武则天与开元盛世
武则天是中国历史上唯一的女皇帝，她统治期间重视人才选拔，社会经济继续发展。
唐玄宗李隆基前期励精图治，任用姚崇宋璟为相，国力达到鼎盛，史称开元盛世。
长安城人口百万，朱雀大街宽阔整齐，东西两市商贾云集，是当时世界闻名的国际大都会。

第三讲 安史之乱与唐朝衰亡
唐玄宗后期朝政腐败，节度使安禄山和部将史思明发动叛乱，史称安史之乱。
安史之乱持续八年，社会经济遭到严重破坏，唐朝从此由盛转衰，形成藩镇割据局面。
唐朝末年爆发黄巢领导的农民大起义，公元九零七年唐朝灭亡，中国进入五代十国时期。

第四讲 唐代文化
唐代诗歌成就辉煌，代表诗人有李白、杜甫、白居易、王维、李商隐等人，作品题材广泛风格多样。
科举制度在唐代得到完善，以明经进士等科考试选拔官吏，扩大了封建王朝的统治基础。
文成公主远嫁吐蕃赞普松赞干布，带去书籍种子工匠，促进了汉藏友好和边疆开发。
"""

TEXT_MATERIALS = [
    ("A班", "生物·光合作用与细胞呼吸.md", "md", BIO_MD),
    ("B班", "历史·唐朝简史.txt", "txt", HIST_TXT),
]


def _get_or_create_class(name: str) -> Class:
    existing = Class.query.filter_by(name=name).first()
    if existing:
        return existing
    created = Class(name=name)
    db.session.add(created)
    db.session.flush()
    return created


def _get_or_create_user(username: str, role: str, class_: Class, password: str) -> User:
    existing = User.query.filter_by(username=username).first()
    if existing:
        return existing
    created = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        class_id=class_.id,
    )
    db.session.add(created)
    db.session.flush()
    return created


def _get_or_create_text_material(
    class_: Class, uploader: User, original_name: str, ext: str, text: str
) -> Material:
    existing = Material.query.filter_by(
        class_id=class_.id, original_name=original_name
    ).first()
    if existing:
        return existing
    stored_key, size_bytes = write_bytes(
        current_app.config["UPLOAD_ROOT"], class_.id, ext, text.encode("utf-8")
    )
    material = Material(
        original_name=original_name,
        stored_key=stored_key,
        mime_type="text/plain",
        size_bytes=size_bytes,
        uploader_id=uploader.id,
        class_id=class_.id,
    )
    db.session.add(material)
    db.session.flush()
    return material


def run_seed(password: str | None = None) -> dict:
    """Create demo data if missing. Safe to run repeatedly."""
    password = password or os.environ.get("SEED_PASSWORD", "campusclaw-demo-123")
    classes = {name: _get_or_create_class(name) for name in ("A班", "B班")}
    for username, role, class_name in DEMO_ACCOUNTS:
        _get_or_create_user(username, role, classes[class_name], password)

    class_a = classes["A班"]
    if not Material.query.filter_by(class_id=class_a.id).first():
        stored_key, size_bytes = write_bytes(
            current_app.config["UPLOAD_ROOT"], class_a.id, "pdf", SAMPLE_PDF
        )
        teacher_a = User.query.filter_by(username="teacher_a").first()
        db.session.add(
            Material(
                original_name="campusclaw-demo.pdf",
                stored_key=stored_key,
                mime_type="application/pdf",
                size_bytes=size_bytes,
                uploader_id=teacher_a.id,
                class_id=class_a.id,
            )
        )

    # Text materials (md/txt) per class; commit rows before best-effort indexing.
    text_materials = []
    for class_name, name, ext, text in TEXT_MATERIALS:
        class_ = classes[class_name]
        uploader = User.query.filter_by(
            username="teacher_a" if class_name == "A班" else "teacher_b"
        ).first()
        text_materials.append(
            _get_or_create_text_material(class_, uploader, name, ext, text)
        )

    db.session.commit()

    # Class A preset skills (idempotent by name). Parse errors would be a
    # programming mistake in presets.py and intentionally surface here.
    from .skills.presets import seed_class_a_skills

    seed_class_a_skills()

    # Class A preset prompt template (idempotent by name).
    from .prompt_templates.presets import seed_class_a_templates

    seed_class_a_templates()

    # Index each material independently: one gateway failure never aborts seed.
    from .kb.indexer import index_material

    for material in text_materials:
        if material.indexed_at is not None:
            continue
        try:
            index_material(material)
        except Exception:  # noqa: BLE001 - isolation is intentional here
            db.session.rollback()
            current_app.logger.warning(
                "seed: indexing material %s failed; left unindexed", material.id
            )

    return {
        "classes": Class.query.count(),
        "users": User.query.count(),
        "materials": Material.query.count(),
    }
