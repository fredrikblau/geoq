# e5embedd.py
import os
import shutil
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.embeddings import SentenceTransformerEmbeddings

load_dotenv()

# ------------------------------------------------------------------
# 1. Manual Entries (clean metadata, use 'category')
# ------------------------------------------------------------------
manual_entries = [
    Document(
        page_content="""
نام: باشگاه بیلیارد اتحاد قشم
نوع: باشگاه بیلیارد، اسنوکر، هشت‌بال

توضیحات:
باشگاه بیلیارد با محیطی دنج و آرام مناسب بازی بیلیارد و اسنوکر 
فضایی دوستانه با حضور بازیکنان سابق تیم ملی
دارای ۳ میز اسنوکر Victorian و ۲ میز بیلیارد

امکانات:
• محیط آرام و حرفه‌ای
• میز اسنوکر و بیلیارد
• مناسب بازیکنان حرفه‌ای و آماتور

آدرس:
خیابان نهضت، روبروی مسجد ایمان، کوچه بین استخر و سوپرمارکت، در فلزی با بنر مجموعه سینمایی

ساعات کاری:
از ۳ عصر تا ۲ الی ۳ نصف شب

شماره تماس:
09170701670
09173632758

لینک نقشه: https://maps.app.goo.gl/TsLp1GoULvJt8HjT8
""".strip(),
        metadata={
            "source": "manual",
            "name": "اتحاد بیلیارد",
            "category": "billiard",
            "tags": "بیلیارد, اسنوکر, تفریح, شبانه",
        },
    ),
    Document(
        page_content="""
نام: کافه بیکری دژاوو قشم
نوع: کافه، بیکری، کتاب‌خوانی

توضیحات:
کافه‌ای زیبا و رمانتیک با محیط آرام و دلنشین
فضای داخلی و بیرونی، مناسب کتاب‌خوانی
محیط مناسب عکاسی و قرارهای دوستانه

امکانات:
• پیانو
• بازی‌های رومیزی
• کتاب
• فضای بیرونی مجزا
• امکان سیگار در فضای بیرون

آدرس:
قشم، نخل زرین، خیابان پژوهش

ساعات کاری:
۸:۳۰ صبح تا ۱ شب
جمعه‌ها ۴ عصر تا ۱ شب

رزرو:
09381326465

اینستاگرام:
https://www.instagram.com/dejavucafe_qeshm

منو:
https://dejavucafeqeshm.ir/shop/49387182
""".strip(),
        metadata={
            "source": "manual",
            "name": "کافه دژاوو",
            "category": "cafe",
            "tags": "کافه, کتاب, موزیک, عکاسی, صبحانه",
        },
    ),
    Document(
        page_content="""
نام: کافه جنوب قشم
نوع: کافه، قهوه تخصصی

توضیحات:
کافه مخصوص قهوه‌ دوستان، مخصوصاً صبح زود
محیط دوستانه با موزیک کلاسیک و امکان سیگار در داخل

آدرس:
گلشهر، خیابان بهشت

ساعات کاری:
۶:۳۰ صبح تا ۱۱ شب

نقشه:
https://maps.google.com/?cid=7680959590059171663&entry=gps
""".strip(),
        metadata={
            "source": "manual",
            "name": "کافه جنوب",
            "category": "cafe",
            "tags": "قهوه, صبحانه, صبح زود, سیگار داخل",
        },
    ),
    Document(
        page_content="""
نام: فروشگاه اکسسوری لیمبو گالری
نوع: فروشگاه اکسسوری و هدایا

توضیحات:
فروشگاه متنوع شامل اکشن فیگور، بدلیجات، دکوری، جوراب، ماگ، جاکلیدی و...

آدرس:
سیتی سنتر ۱، طبقه اول، لاین N2، پلاک ۲۱۸۸

ساعات کاری:
۱۱ تا ۲ ظهر
۵ تا ۱۱ شب

تماس:
09203642114

اینستاگرام:
https://www.instagram.com/limbogalleryy
""".strip(),
        metadata={
            "source": "manual",
            "name": "لیمبو گالری",
            "category": "shop",
            "tags": "اکسسوری, ماگ, کادو, دکوری, هنری",
        },
    ),
    Document(
        page_content="""
نام: شهربازی سیتی سنتر قشم
نوع: شهربازی، فودکورت، بولینگ، بیلیارد

توضیحات:
بزرگترین شهربازی سرپوشیده قشم
دارای بیش از ۲۴۰ دستگاه بازی
سالن بولینگ و بیلیارد
گیم‌نت و سینمای ۴ بعدی

آدرس:
قشم، بلوار دریا، سیتی سنتر ۱، طبقه سوم

تماس:
07635241501
""".strip(),
        metadata={
            "source": "manual",
            "name": "شهربازی سیتی سنتر",
            "category": "arcade",
            "tags": "سرگرمی, تفریح, بازی, کودکان, خانوادگی",
        },
    ),
    Document(
        page_content="""
کافه لامور 
توضیح:
محیطی ایده‌آل و خودمانی با تمرکز ویژه بر شیرینی‌ها، کیک‌ها و تارت‌های فرانسوی خوش‌طعم. یکی از کافه‌های پرطرفدار و باکیفیت قشم.
امکانات: 
کیک، تارت و شیرینی‌های فرانسوی، فضای دنج.
آدرس: 
قشم، میدان گلدن سیتی، خیابان داماس، مجتمع تجاری داماس.
تایم کاری:
10:00 صبح تا 12:00 شب.
شماره جهت رزرو:
07633389109 - 09179554979
اینستاگرام: https://www.instagram.com/cafelamour.qeshm
""".strip(),
        metadata={
            "source": "manual",
            "name": "کافه لامور",
            "category": "cafe",
            "tags": "کافه, دنج, دسر, شیرینی, فرانسوی",
        },
    ),
    Document(
        page_content="""
بوتیک کیک و کافه سدنا 
توضیح: 
معروف به "کافه صورتی" قشم. دکوراسیون خاص و شاد، بهشتی برای عاشقان شیرینی و کیک. محیطی عالی برای عکاسی‌های اینستاگرامی.
امکانات:
بوتیک کیک و شیرینی تازه، دکوراسیون صورتی خاص، مناسب عکاسی.
آدرس:
خیابان سرخس ، میدان طالقانی ، قبل از کتابخانه اندیشه ، مجتمع داماش 
تایم کاری: 
حدود 10:00 صبح تا 11:00 شب(جمعه‌ها از 5 عصر).
شماره جهت رزرو: 
09177698839
اینستاگرام: https://www.instagram.com/sedna_bfst
""".strip(),
        metadata={
            "source": "manual",
            "name": "بوتیک کیک و کافه سدنا",
            "category": "cafe",
            "tags": "کافه, دسر, عکاسی, صورتی, کیک",
        },
    ),
    Document(
        page_content="""
کافه رستوران ساحلی دریم لند 
توضیح:
کافه رستوران لوکس با ویوی رو به دریا و ساحل اختصاصی. مناسب برای یک تجربه ساحلی و شیک در قشم. اجرای موزیک زنده دارد.
امکانات: 
ویوی دریا، ساحل، موزیک زنده، منوی متنوع (نوشیدنی و غذا).
آدرس: 
قشم، جنب سینما دریا، بعد از سیتی سنتر 2.
تایم کاری:
13:00 (1 ظهر) الی 1 بامداد.
شماره جهت رزرو: 09171350064
اینستاگرام: https://www.instagram.com/dreamland.qeshm
""".strip(),
        metadata={
            "source": "manual",
            "name": "کافه رستوران ساحلی دریم لند",
            "category": "cafe",
            "tags": "کافه, دریا, موزیک زنده, ساحلی, لوکس",
        },
    ),
    Document(
        page_content="""
کافه دالاهو 
توضیح:
کافه‌ای با فضای سنتی و دلنشین که اغلب با اجرای موسیقی زنده محلی همراه است. همچنین به عنوان یکی از بهترین کافه‌قلیان‌های قشم شناخته می‌شود.
امکانات:
فضای سنتی و دلنشین، موسیقی زنده محلی، قلیان.
آدرس:
قشم، خیابان فلسطین، خیابان بهشت.
تایم کاری:
(اطلاعات کامل در دسترس نیست)
""".strip(),
        metadata={
            "source": "manual",
            "name": "کافه دالاهو",
            "category": "cafe",
            "tags": "کافه, سنتی, قلیان, موسیقی زنده",
        },
    ),
    Document(
        page_content="""
کافه و گالری عود 
توضیح: 
کافه‌ای با فضای هنری و گالری، محیطی متفاوت و خاص در منطقه طبل.
امکانات:
گالری، فضای هنری، نوشیدنی.
آدرس:
قشم، شهر طبل، جاده سلخ.
تایم کاری:
(اطلاعات کامل در دسترس نیست)
شماره جهت رزرو:
09112770407
اینستاگرام: https://www.instagram.com/oud.gallery_cafe
""".strip(),
        metadata={
            "source": "manual",
            "name": "کافه و گالری عود",
            "category": "cafe",
            "tags": "کافه, هنری, گالری, طبل",
        },
    ),
]

# ------------------------------------------------------------------
# 2. Smart Chunking (preserve structure)
# ------------------------------------------------------------------
splitter = RecursiveCharacterTextSplitter(
    chunk_size=600,
    chunk_overlap=150,
    separators=["\n\n", "\n", " ", ""],
    keep_separator=True,
)
chunks = splitter.split_documents(manual_entries)

# Clean whitespace
for doc in chunks:
    doc.page_content = " ".join(doc.page_content.split())

# ------------------------------------------------------------------
# 3. Embeddings (e5-large + normalize)
# ------------------------------------------------------------------
embeddings = SentenceTransformerEmbeddings(
    model_name="intfloat/multilingual-e5-large",
    encode_kwargs={"normalize_embeddings": True},
)

# ------------------------------------------------------------------
# 4. Fresh DB (delete old if exists)
# ------------------------------------------------------------------
db_path = "qeshm_db"
if os.path.exists(db_path):
    shutil.rmtree(db_path)
    print(f"Deleted old DB: {db_path}")

db = Chroma(persist_directory=db_path, embedding_function=embeddings)
db.add_documents(chunks)
db.persist()

print(f"Added {len(chunks)} chunks → {db_path} (1024-dim e5-large)")
