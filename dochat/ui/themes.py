"""채팅 버블 색상 테마 프리셋과 현재 적용 색상을 계산하는 유틸리티."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BubbleTheme:
    name: str
    mine_bg: str
    mine_text: str
    other_bg: str
    other_text: str


THEMES: dict[str, BubbleTheme] = {
    "blue": BubbleTheme("블루(기본)", "#3B6FE0", "#FFFFFF", "#F0F1F4", "#2C2F36"),
    "green": BubbleTheme("그린", "#2E9E6B", "#FFFFFF", "#EFF3F1", "#2C2F36"),
    "purple": BubbleTheme("퍼플", "#7C5CD6", "#FFFFFF", "#F1EFF6", "#2C2F36"),
    "dark": BubbleTheme("다크", "#4C8DFF", "#FFFFFF", "#3A3D45", "#EDEEF2"),
}
DEFAULT_THEME_KEY = "blue"


def get_theme_colors(storage) -> tuple[str, str, str, str]:
    """storage 설정을 바탕으로 (mine_bg, mine_text, other_bg, other_text)를 반환한다.

    우선순위: 커스텀 색(설정에서 직접 고른 경우) > 선택된 테마 프리셋 > 기본 테마.
    storage가 None이면(폴백) 기본 테마 색을 그대로 반환한다.
    """
    if storage is None:
        theme = THEMES[DEFAULT_THEME_KEY]
        return theme.mine_bg, theme.mine_text, theme.other_bg, theme.other_text

    theme_key = storage.get_setting("bubble_theme", DEFAULT_THEME_KEY)
    theme = THEMES.get(theme_key, THEMES[DEFAULT_THEME_KEY])

    mine_bg = storage.get_setting("bubble_mine_color") or theme.mine_bg
    other_bg = storage.get_setting("bubble_other_color") or theme.other_bg
    mine_text = theme.mine_text
    other_text = theme.other_text
    return mine_bg, mine_text, other_bg, other_text
