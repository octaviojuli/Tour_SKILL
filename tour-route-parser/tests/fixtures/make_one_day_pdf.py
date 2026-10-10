"""Regenerate tests/fixtures/acme-one-day.pdf: a fictional ACME 一日游 laid out like the
supplier one-day sheets in the field test (time-ordered programme, no 第X天 headers,
terms after the programme). Needs reportlab and the WenQuanYi Zen Hei font (embedded as a subset, so the PDF
carries a real text layer like supplier files do); the PDF is committed so tests do not.

    python tests/fixtures/make_one_day_pdf.py
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

LINES = [
    "ACME 古镇土楼经典一日游",
    "纯玩 0 购物 · 每天发团 · 厦门市区酒店接送",
    "行程安排",
    "07:30 厦门市区指定酒店接客人，乘车前往 ACME 古镇（车程约 2.5 小时）",
    "10:00 抵达 ACME 古镇，游览百年老街与水车（含门票，游览约 1.5 小时）",
    "12:00 享用中餐（含团餐，十人一桌）",
    "13:30 前往 ACME 土楼群，参观【ACME 和贵楼】（入内参观，约 1 小时）",
    "15:30 车游 ACME 溪畔景观带，途经【ACME 古榕】",
    "18:30 返回厦门市区，结束愉快行程",
    "费用包含",
    "1、全程空调旅游车；2、景点首道门票；3、一正餐；4、中文导游服务",
    "费用不含",
    "1、个人消费；2、景区内电瓶车 20 元/人（自理）",
    "温馨提示",
    "请携带身份证件，按约定时间在酒店大堂等候。",
]


def main() -> None:
    pdfmetrics.registerFont(TTFont("ZenHei", FONT, subfontIndex=0))
    out = Path(__file__).with_name("acme-one-day.pdf")
    page = canvas.Canvas(str(out), pagesize=A4, invariant=1)  # invariant: byte-stable output
    page.setFont("ZenHei", 11)
    y = 800
    for line in LINES:
        page.drawString(40, y, line)
        y -= 26
    page.save()
    print(out)


if __name__ == "__main__":
    main()
