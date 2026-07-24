"""앱 전체 QSS 템플릿.

원본 정적 스타일시트(``dochat/ui/styles.qss``)를 기반으로, 테마에 따라
바뀌어야 하는 색상값들을 ``str.format`` 플레이스홀더로 치환한 문자열이다.
실제 QSS 문자열은 ``dochat.ui.themes.render_stylesheet(storage)``가
``STYLE_TEMPLATE.format(...)``으로 생성한다.

사용 가능한 플레이스홀더:
    {accent} {accent_hover} {accent_pressed}
    {app_bg} {sidebar_bg} {border}
    {text_primary} {text_secondary}
    {selection_bg} {hover_bg}
    {font_family} {font_size}

주의: QSS의 블록 구분자 ``{``/``}``는 ``str.format``과 충돌하므로 모두
``{{``/``}}``로 이스케이프되어 있다. (원본 ``styles.qss`` 파일 자체는
삭제하지 않고 그대로 남겨두었다.)
"""
from __future__ import annotations

STYLE_TEMPLATE = """/* DoChat - 오피스 스타일 스타일시트 (테마 대응)
   dochat.ui.themes.render_stylesheet()가 채팅 테마 설정에 맞춰
   아래 플레이스홀더들을 실제 색상값으로 채워 넣는다.
*/

* {{
    font-family: {font_family};
    outline: none;
}}

QWidget {{
    background-color: {app_bg};
    color: {text_primary};
    font-size: {font_size}px;
}}

QMainWindow {{
    background-color: {app_bg};
}}

/* ---------------- 사이드바 ---------------- */
#Sidebar {{
    background-color: {sidebar_bg};
    border-right: 1px solid {border};
}}

#SidebarHeader {{
    background-color: {sidebar_bg};
    border-bottom: 1px solid {border};
}}

#AppTitle {{
    color: {text_primary};
    font-size: 16px;
    font-weight: 600;
}}

QPushButton#SidebarActionButton {{
    background-color: {app_bg};
    color: {accent};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 9px 12px;
    min-height: 18px;
    font-weight: 600;
}}

QPushButton#SidebarActionButton:hover {{
    background-color: {hover_bg};
    border: 1px solid {accent};
}}

QPushButton#SidebarActionButton:pressed {{
    background-color: {selection_bg};
}}

#SidebarFooter {{
    background-color: {sidebar_bg};
    border-top: 1px solid {border};
}}

#VersionLabel {{
    color: {text_secondary};
    font-size: 11px;
    background: transparent;
}}

QPushButton#QuitButton {{
    background-color: transparent;
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 12px;
    color: #C0392B;
    font-size: 12px;
}}

QPushButton#QuitButton:hover {{
    background-color: #FBEAEA;
    border: 1px solid #E0433B;
}}

/* ---------------- 대화 목록 ---------------- */
QListWidget#ConversationList {{
    background-color: {sidebar_bg};
    border: none;
    padding: 4px;
}}

QListWidget#ConversationList::item {{
    background-color: transparent;
    border-radius: 8px;
    padding: 0px;
    margin: 2px 4px;
}}

QListWidget#ConversationList::item:selected {{
    background-color: {selection_bg};
}}

QListWidget#ConversationList::item:hover:!selected {{
    background-color: #ECEDF1;
}}

/* ---------------- 채팅 영역 헤더 ---------------- */
#ChatHeader {{
    background-color: {app_bg};
    border-bottom: 1px solid {border};
}}

#ChatHeaderTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {text_primary};
}}

#ChatHeaderSubtitle {{
    font-size: 12px;
    color: {text_secondary};
}}

/* ---------------- 채팅 영역 ---------------- */
QScrollArea#ChatScrollArea {{
    background-color: {app_bg};
    border: none;
}}

#ChatViewport {{
    background-color: {app_bg};
}}

#EmptyStateLabel {{
    color: {text_secondary};
    font-size: 13px;
}}

/* 말풍선 (실제로는 message_bubble.py가 인라인 스타일로 직접 칠하므로
   아래 셀렉터들은 폴백/참고용이며 대응하는 앱 테마 색으로 치환해 둔다) */
#BubbleFrameMine {{
    background-color: {accent};
    border-radius: 16px;
}}

#BubbleFrameOther {{
    background-color: {hover_bg};
    border: 1px solid {border};
    border-radius: 16px;
}}

#BubbleTextMine {{
    color: #FFFFFF;
    background: transparent;
}}

#BubbleTextOther {{
    color: {text_primary};
    background: transparent;
}}

#BubbleMeta {{
    color: {text_secondary};
    font-size: 11px;
    background: transparent;
}}

#BubbleMetaMine {{
    color: #DCE5FA;
    font-size: 11px;
    background: transparent;
}}

#BubbleSender {{
    color: {accent};
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}}

#FileCard {{
    background-color: rgba(255, 255, 255, 0.12);
    border-radius: 8px;
}}

#FileCardOther {{
    background-color: {app_bg};
    border: 1px solid {border};
    border-radius: 8px;
}}

#FileNameLabel {{
    font-weight: 600;
    background: transparent;
}}

#FileMetaLabel {{
    color: {text_secondary};
    font-size: 11px;
    background: transparent;
}}

/* ---------------- 입력창 영역 ---------------- */
#ComposeBar {{
    background-color: {app_bg};
    border-top: 1px solid {border};
}}

QLineEdit#ComposeInput {{
    background-color: {sidebar_bg};
    border: 1px solid {border};
    border-radius: 18px;
    padding: 9px 16px;
    font-size: 13px;
    color: {text_primary};
}}

QLineEdit#ComposeInput:focus {{
    border: 1px solid {accent};
    background-color: {app_bg};
}}

QPushButton#AttachButton {{
    background-color: transparent;
    border: none;
    border-radius: 16px;
    font-size: 16px;
    color: {text_secondary};
    padding: 6px;
}}

QPushButton#AttachButton:hover {{
    background-color: {hover_bg};
    color: {accent};
}}

QPushButton#SendButton {{
    background-color: {accent};
    color: #FFFFFF;
    border: none;
    border-radius: 18px;
    padding: 8px 20px;
    font-weight: 600;
}}

QPushButton#SendButton:hover {{
    background-color: {accent_hover};
}}

QPushButton#SendButton:pressed {{
    background-color: {accent_pressed};
}}

QPushButton#SendButton:disabled {{
    background-color: #C7D2F2;
    color: #FFFFFF;
}}

/* ---------------- 공용 위젯 ---------------- */
QPushButton {{
    background-color: {app_bg};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 6px 14px;
    color: {text_primary};
}}

QPushButton:hover {{
    background-color: {hover_bg};
}}

QPushButton:pressed {{
    background-color: {border};
}}

QPushButton#PrimaryButton {{
    background-color: {accent};
    border: none;
    color: #FFFFFF;
    font-weight: 600;
}}

QPushButton#PrimaryButton:hover {{
    background-color: {accent_hover};
}}

QPushButton#PrimaryButton:pressed {{
    background-color: {accent_pressed};
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {app_bg};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 6px 10px;
    color: {text_primary};
    selection-background-color: {accent};
    selection-color: #FFFFFF;
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {accent};
}}

QListWidget {{
    background-color: {app_bg};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 4px;
}}

QListWidget::item {{
    padding: 6px 8px;
    border-radius: 6px;
}}

QListWidget::item:selected {{
    background-color: {selection_bg};
    color: {text_primary};
}}

QListWidget::item:hover:!selected {{
    background-color: {hover_bg};
}}

QProgressBar {{
    background-color: rgba(255, 255, 255, 0.25);
    border: none;
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: #FFFFFF;
    border-radius: 5px;
}}

QProgressBar#FileProgressOther {{
    background-color: {border};
}}

QProgressBar#FileProgressOther::chunk {{
    background-color: {accent};
    border-radius: 5px;
}}

QDialog {{
    background-color: {app_bg};
}}

QLabel#DialogLabel {{
    color: {text_primary};
    font-weight: 600;
}}

QLabel#DialogHint {{
    color: {text_secondary};
    font-size: 11px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: #D3D6DC;
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: #B7BBC2;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: #D3D6DC;
    border-radius: 5px;
    min-width: 24px;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QMenu {{
    background-color: {app_bg};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 16px;
    border-radius: 6px;
}}

QMenu::item:selected {{
    background-color: {selection_bg};
}}

QToolTip {{
    background-color: {text_primary};
    color: #FFFFFF;
    border: none;
    padding: 4px 8px;
    border-radius: 4px;
}}
"""
