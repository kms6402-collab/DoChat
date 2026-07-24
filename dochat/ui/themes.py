"""채팅 버블 색상 테마 프리셋과 현재 적용 색상을 계산하는 유틸리티.

앱 전체(사이드바/버튼/배경/헤더 등)에 적용되는 색상 토큰도 함께 관리한다.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class BubbleTheme:
    name: str
    mine_bg: str
    mine_text: str
    other_bg: str
    other_text: str
    # --- 앱 전체 팔레트 (신규) ---
    accent: str = "#3B6FE0"           # 포인트 컬러 (버튼/선택 강조)
    accent_hover: str = "#2F5BC4"
    accent_pressed: str = "#274CA6"
    app_bg: str = "#FFFFFF"           # 메인 배경
    sidebar_bg: str = "#F5F6F8"       # 사이드바/헤더 배경
    border: str = "#E4E6EA"           # 구분선/보더
    text_primary: str = "#2C2F36"     # 기본 텍스트
    text_secondary: str = "#8A8F98"   # 보조 텍스트
    selection_bg: str = "#E3EAFB"     # 선택된 항목 강조 배경 (연한 포인트색)
    hover_bg: str = "#F0F1F4"         # 호버 시 배경


THEMES: dict[str, BubbleTheme] = {
    "blue": BubbleTheme(
        "블루(기본)", "#3B6FE0", "#FFFFFF", "#F0F1F4", "#2C2F36",
        accent="#3B6FE0", accent_hover="#2F5BC4", accent_pressed="#274CA6",
        app_bg="#FFFFFF", sidebar_bg="#F5F6F8", border="#E4E6EA",
        text_primary="#2C2F36", text_secondary="#8A8F98",
        selection_bg="#E3EAFB", hover_bg="#F0F1F4",
    ),
    "green": BubbleTheme(
        "그린", "#2E9E6B", "#FFFFFF", "#EFF3F1", "#2C2F36",
        accent="#2E9E6B", accent_hover="#278A5D", accent_pressed="#1F6F4A",
        app_bg="#FFFFFF", sidebar_bg="#F5F6F8", border="#E4E6EA",
        text_primary="#2C2F36", text_secondary="#8A8F98",
        selection_bg="#DFF3E9", hover_bg="#EEF7F2",
    ),
    "purple": BubbleTheme(
        "퍼플", "#7C5CD6", "#FFFFFF", "#F1EFF6", "#2C2F36",
        accent="#7C5CD6", accent_hover="#6B4CC4", accent_pressed="#5A3FB0",
        app_bg="#FFFFFF", sidebar_bg="#F5F6F8", border="#E4E6EA",
        text_primary="#2C2F36", text_secondary="#8A8F98",
        selection_bg="#EDE8FA", hover_bg="#F3F0FA",
    ),
    "dark": BubbleTheme(
        "다크", "#4C8DFF", "#FFFFFF", "#3A3D45", "#EDEEF2",
        accent="#4C8DFF", accent_hover="#3D7AE0", accent_pressed="#2F63C2",
        app_bg="#1E1F24", sidebar_bg="#17181C", border="#2E3038",
        text_primary="#EDEEF2", text_secondary="#9A9EA8",
        selection_bg="#26314A", hover_bg="#24262C",
    ),
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


def get_app_theme(storage) -> BubbleTheme:
    """storage 설정을 반영한 앱 전체 테마 객체를 반환한다.

    말풍선 커스텀 색(내/상대 말풍선 색)만 오버라이드하고, 나머지 앱 전체
    팔레트(accent/app_bg/sidebar_bg 등)는 선택된 테마 프리셋 값을 그대로 사용한다.
    storage가 None이면(폴백) 기본 테마를 그대로 반환한다.
    """
    if storage is None:
        return THEMES[DEFAULT_THEME_KEY]

    theme_key = storage.get_setting("bubble_theme", DEFAULT_THEME_KEY)
    theme = THEMES.get(theme_key, THEMES[DEFAULT_THEME_KEY])

    mine_bg = storage.get_setting("bubble_mine_color") or theme.mine_bg
    other_bg = storage.get_setting("bubble_other_color") or theme.other_bg
    return replace(theme, mine_bg=mine_bg, other_bg=other_bg)


def render_stylesheet(storage) -> str:
    """현재 테마 설정을 반영한 앱 전체 QSS 문자열을 생성해 반환한다."""
    from dochat.ui.style_template import STYLE_TEMPLATE

    theme = get_app_theme(storage)
    return STYLE_TEMPLATE.format(
        accent=theme.accent,
        accent_hover=theme.accent_hover,
        accent_pressed=theme.accent_pressed,
        app_bg=theme.app_bg,
        sidebar_bg=theme.sidebar_bg,
        border=theme.border,
        text_primary=theme.text_primary,
        text_secondary=theme.text_secondary,
        selection_bg=theme.selection_bg,
        hover_bg=theme.hover_bg,
    )
