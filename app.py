import streamlit as st
import anthropic
import requests
import json

# ─────────────────────────────────────────
# Notion API 함수들
# ─────────────────────────────────────────

def search_notion(query: str, notion_token: str) -> list[dict]:
    """노션에서 키워드로 페이지 검색"""
    url = "https://api.notion.com/v1/search"
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    body = {
        "query": query,
        "filter": {"value": "page", "property": "object"},
        "page_size": 5,  # 상위 5개 페이지만 가져오기
    }
    resp = requests.post(url, headers=headers, json=body)
    if resp.status_code != 200:
        return []
    return resp.json().get("results", [])


def get_page_content(page_id: str, notion_token: str) -> str:
    """페이지 본문(블록) 텍스트 추출"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": "2022-06-28",
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return ""

    blocks = resp.json().get("results", [])
    texts = []
    for block in blocks:
        btype = block.get("type", "")
        # 텍스트가 있는 블록 유형들
        if btype in ["paragraph", "heading_1", "heading_2", "heading_3",
                     "bulleted_list_item", "numbered_list_item", "to_do",
                     "toggle", "quote", "callout"]:
            rich_texts = block.get(btype, {}).get("rich_text", [])
            line = "".join(rt.get("plain_text", "") for rt in rich_texts)
            if line.strip():
                texts.append(line)
        # 하위 블록도 재귀적으로 읽기 (1단계만)
        if block.get("has_children"):
            child_text = get_page_content(block["id"], notion_token)
            if child_text:
                texts.append(child_text)

    return "\n".join(texts)


def get_page_title(page: dict) -> str:
    """페이지 제목 추출"""
    props = page.get("properties", {})
    # title 또는 Name 속성에서 찾기
    for key in ["title", "Title", "Name", "이름"]:
        if key in props:
            rich_texts = props[key].get("title", [])
            title = "".join(rt.get("plain_text", "") for rt in rich_texts)
            if title:
                return title
    return "제목 없음"


def get_page_url(page: dict) -> str:
    """페이지 URL 반환"""
    return page.get("url", "")


# ─────────────────────────────────────────
# Claude API 함수
# ─────────────────────────────────────────

def ask_claude(question: str, context: str, claude_api_key: str) -> str:
    """노션 내용을 컨텍스트로 Claude에게 답변 요청"""
    client = anthropic.Anthropic(api_key=claude_api_key)

    system_prompt = """당신은 대학교 행정실의 친절한 안내 도우미입니다.
아래 노션 문서 내용을 바탕으로 직원들의 질문에 답변하세요.

규칙:
1. 노션 문서에 있는 내용만 답변하세요.
2. 문서에 없는 내용이면 "해당 내용은 문서에서 찾을 수 없습니다. 담당자에게 직접 문의해 주세요."라고 답하세요.
3. 답변은 간결하고 명확하게 해주세요.
4. 번호나 불릿 포인트를 활용해 읽기 쉽게 구성해주세요."""

    user_message = f"""[노션 문서 내용]
{context}

[질문]
{question}"""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


# ─────────────────────────────────────────
# Streamlit 화면
# ─────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="행정실 안내 챗봇",
        page_icon="🏫",
        layout="centered",
    )

    st.title("🏫 행정실 안내 챗봇")
    st.caption("노션 문서를 기반으로 답변합니다")

    # ── 사이드바: API 키 입력 (또는 환경변수에서 자동 로드)
    with st.sidebar:
        st.header("⚙️ 설정")
        notion_token = st.text_input(
            "Notion API 키",
            type="password",
            value=st.secrets.get("NOTION_TOKEN", ""),
            help="secret_xxx... 형식",
        )
        claude_key = st.text_input(
            "Claude API 키",
            type="password",
            value=st.secrets.get("CLAUDE_API_KEY", ""),
            help="sk-ant-xxx... 형식",
        )
        st.divider()
        st.markdown("**사용 방법**")
        st.markdown("1. 위에 API 키 입력\n2. 궁금한 내용 입력\n3. Enter 또는 전송 버튼")

    # ── 대화 기록 초기화
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # ── 이전 대화 표시
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── 사용자 입력
    if question := st.chat_input("무엇이 궁금하신가요? (예: 연가 신청 방법)"):

        # API 키 확인
        if not notion_token or not claude_key:
            st.error("왼쪽 사이드바에서 API 키를 입력해주세요.")
            st.stop()

        # 사용자 메시지 표시
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        # 답변 생성
        with st.chat_message("assistant"):
            with st.spinner("노션에서 관련 내용을 찾는 중..."):

                # 1) 노션 검색
                pages = search_notion(question, notion_token)

                if not pages:
                    answer = "관련 문서를 찾을 수 없습니다. 담당자에게 직접 문의해 주세요."
                    sources = []
                else:
                    # 2) 각 페이지 본문 수집
                    context_parts = []
                    sources = []
                    for page in pages:
                        title = get_page_title(page)
                        page_id = page["id"]
                        url = get_page_url(page)
                        content = get_page_content(page_id, notion_token)

                        if content.strip():
                            context_parts.append(
                                f"## {title}\n{content}"
                            )
                            sources.append({"title": title, "url": url})

                    if not context_parts:
                        answer = "관련 문서를 찾았으나 내용이 비어 있습니다. 노션 페이지에 본문 내용을 추가해주세요."
                    else:
                        context = "\n\n".join(context_parts)
                        # 3) Claude 답변 생성
                        answer = ask_claude(question, context, claude_key)

            # 답변 표시
            st.markdown(answer)

            # 출처 표시
            if sources:
                with st.expander("📄 참고한 노션 문서"):
                    for s in sources:
                        st.markdown(f"- [{s['title']}]({s['url']})")

        # 대화 기록 저장
        st.session_state.messages.append({"role": "assistant", "content": answer})

    # ── 대화 초기화 버튼
    if st.session_state.messages:
        if st.button("🗑️ 대화 초기화"):
            st.session_state.messages = []
            st.rerun()


if __name__ == "__main__":
    main()