"""DoChat 프로그램 아이콘 생성 스크립트.

이 스크립트는 외부 이미지 생성 도구 없이 Pillow만으로 DoChat 앱 아이콘을 그린다.
4096x4096 크기로 그린 뒤 1024x1024로 축소(LANCZOS)해서 anti-aliasing 품질을 확보한다.

사용법:
    python assets/generate_icon.py

결과물:
    assets/icon_master.png  (1024x1024 마스터 PNG)
    assets/icon.png         (256x256, 앱 내부/창 아이콘용)

주의: assets/icon.ico, assets/icon.icns 는 이 스크립트가 아니라
별도 변환 절차(icon_master.png 로부터 생성)로 만든다.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# DoChat 확정 팔레트 (dochat/ui/styles.qss 참고)
POINT_BLUE = "#3B6FE0"
WHITE = "#FFFFFF"

ASSETS_DIR = Path(__file__).resolve().parent

# 4배 크기로 그려서 축소하는 슈퍼샘플링 방식
SCALE = 4
FINAL_SIZE = 1024
CANVAS_SIZE = FINAL_SIZE * SCALE


def draw_icon() -> Image.Image:
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # 1) 배경: 둥근 사각형, 포인트 블루로 캔버스 대부분을 채움 (여백 최소화)
    margin = int(CANVAS_SIZE * 0.02)
    bg_radius = int(CANVAS_SIZE * 0.22)
    draw.rounded_rectangle(
        [margin, margin, CANVAS_SIZE - margin, CANVAS_SIZE - margin],
        radius=bg_radius,
        fill=POINT_BLUE,
    )

    # 2) 말풍선 본체: 흰색 둥근 사각형
    bubble_left = int(CANVAS_SIZE * 0.16)
    bubble_top = int(CANVAS_SIZE * 0.20)
    bubble_right = int(CANVAS_SIZE * 0.84)
    bubble_bottom = int(CANVAS_SIZE * 0.68)
    bubble_radius = int(CANVAS_SIZE * 0.13)
    draw.rounded_rectangle(
        [bubble_left, bubble_top, bubble_right, bubble_bottom],
        radius=bubble_radius,
        fill=WHITE,
    )

    # 3) 말풍선 꼬리(tail): 아래쪽 왼쪽에 작은 삼각형
    tail_base_x = int(CANVAS_SIZE * 0.30)
    tail_tip_x = int(CANVAS_SIZE * 0.24)
    tail_top_y = bubble_bottom - int(CANVAS_SIZE * 0.02)
    tail_tip_y = int(CANVAS_SIZE * 0.80)
    draw.polygon(
        [
            (tail_base_x, tail_top_y),
            (tail_base_x + int(CANVAS_SIZE * 0.14), tail_top_y),
            (tail_tip_x, tail_tip_y),
        ],
        fill=WHITE,
    )

    # 4) 말풍선 내부: 채팅을 나타내는 점 3개(말줄임표 느낌), 포인트 블루
    dot_radius = int(CANVAS_SIZE * 0.035)
    bubble_center_y = (bubble_top + bubble_bottom) // 2
    dot_spacing = int(CANVAS_SIZE * 0.16)
    bubble_center_x = (bubble_left + bubble_right) // 2
    for offset in (-1, 0, 1):
        cx = bubble_center_x + offset * dot_spacing
        cy = bubble_center_y
        draw.ellipse(
            [cx - dot_radius, cy - dot_radius, cx + dot_radius, cy + dot_radius],
            fill=POINT_BLUE,
        )

    return canvas


def main() -> None:
    canvas = draw_icon()
    master = canvas.resize((FINAL_SIZE, FINAL_SIZE), Image.LANCZOS)

    master_path = ASSETS_DIR / "icon_master.png"
    master.save(master_path, format="PNG")
    print(f"저장됨: {master_path}")

    app_icon = master.resize((256, 256), Image.LANCZOS)
    app_icon_path = ASSETS_DIR / "icon.png"
    app_icon.save(app_icon_path, format="PNG")
    print(f"저장됨: {app_icon_path}")


if __name__ == "__main__":
    main()
