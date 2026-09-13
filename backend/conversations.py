"""로컬 단일 사용자의 대화방·메시지를 SQLite에 저장하는 API."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.portfolio import require_local

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "chat.sqlite3"
LOCAL_USER = "local"
router = APIRouter(prefix="/api/conversations", dependencies=[Depends(require_local)])


@contextmanager
def _connection():
    """연결마다 트랜잭션을 완료하거나 롤백하고 반드시 닫는다."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    """서버 시작 시 로컬 DB를 생성하고 남은 pending 응답을 interrupted로 바꾼다.

    인자·외부 호출 없음. 단일 서버 프로세스를 전제로 하며 SQLite/파일 오류는 전달한다.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'completed', 'error', 'interrupted')),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(conversations)")}
        if "summary" not in columns:
            db.execute("ALTER TABLE conversations ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
        if "last_summarized_message_id" not in columns:
            db.execute("ALTER TABLE conversations ADD COLUMN last_summarized_message_id INTEGER")
        db.execute("UPDATE messages SET status = 'interrupted', content = ? WHERE status = 'pending'",
                   ("서버가 재시작되어 응답이 중단되었습니다. 다시 질문해주세요.",))


def _conversation(db, conversation_id: str):
    """현재 로컬 사용자의 대화방만 조회하며 없으면 404를 반환한다."""
    row = db.execute("SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                     (conversation_id, LOCAL_USER)).fetchone()
    if row is None:
        raise HTTPException(404, "대화방을 찾을 수 없습니다.")
    return dict(row)


def _require_idle(db, conversation_id: str):
    """같은 대화의 동시 요청·실행 중 삭제를 거부한다."""
    if db.execute("SELECT 1 FROM messages WHERE conversation_id = ? AND status = 'pending'",
                  (conversation_id,)).fetchone():
        raise HTTPException(409, "이 대화에서 답변을 생성 중입니다. 완료 후 다시 시도하세요.")


@router.get("")
def list_conversations() -> list[dict]:
    """로컬 사용자의 대화방을 최근 활동 순으로 반환한다. DB 읽기 오류는 전달한다."""
    with _connection() as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC, id",
            (LOCAL_USER,),
        )]


@router.post("", status_code=201)
def create_conversation() -> dict:
    """로컬 사용자에게 빈 대화방을 생성·반환한다. DB 쓰기 오류는 전달한다."""
    now = datetime.now(timezone.utc).isoformat()
    conversation_id = str(uuid4())
    with _connection() as db:
        db.execute("INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                   (conversation_id, LOCAL_USER, "새 대화", now, now))
        return _conversation(db, conversation_id)


@router.get("/{conversation_id}")
def get_conversation(conversation_id: UUID) -> dict:
    """대화 UUID로 소유 대화와 메시지를 입력 순서대로 반환한다. 없으면 404다."""
    with _connection() as db:
        result = _conversation(db, str(conversation_id))
        result["messages"] = [dict(row) for row in db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (str(conversation_id),),
        )]
        return result


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID) -> Response:
    """대화와 메시지를 함께 삭제한다. 없는 대화는 404, 생성 중이면 409다."""
    with _connection() as db:
        db.execute("BEGIN IMMEDIATE")
        _conversation(db, str(conversation_id))
        _require_idle(db, str(conversation_id))
        db.execute("DELETE FROM conversations WHERE id = ?", (str(conversation_id),))
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


def begin_turn(conversation_id: str, message: str) -> int:
    """대화에 질문과 pending 답변을 원자적으로 저장하고 답변 ID를 반환한다.

    첫 질문을 제목으로 사용한다. 소유 대화가 없으면 404, 실행 중이면 409이며
    실패 시 메시지를 저장하지 않는다. 모델·계좌 호출은 없다.
    """
    with _connection() as db:
        db.execute("BEGIN IMMEDIATE")
        _conversation(db, conversation_id)
        _require_idle(db, conversation_id)
        first = not db.execute("SELECT 1 FROM messages WHERE conversation_id = ?",
                               (conversation_id,)).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO messages (conversation_id, role, content, status, created_at) VALUES (?, 'user', ?, 'completed', ?)",
                   (conversation_id, message, now))
        cursor = db.execute("INSERT INTO messages (conversation_id, role, content, status, created_at) VALUES (?, 'assistant', '', 'pending', ?)",
                            (conversation_id, now))
        db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        if first:
            db.execute("UPDATE conversations SET title = ? WHERE id = ?",
                       (" ".join(message.split())[:40], conversation_id))
        return cursor.lastrowid


def finish_turn(message_id: int, content: str, status: str) -> None:
    """pending 답변을 최종 내용·상태로 한 번만 갱신한다. DB 오류는 전달한다.

    모델 출력 또는 정제된 오류 문구만 저장한다. Tool 결과와 계좌 원문은 받지 않는다.
    """
    with _connection() as db:
        db.execute("UPDATE messages SET content = ?, status = ? WHERE id = ? AND status = 'pending'",
                   (content, status, message_id))


def load_memory_turns(message_id: int) -> tuple[dict, list[list[dict]]]:
    """현재 pending 답변 ID로 세션 요약과 그 이전의 미요약 완료 턴을 읽는다.

    실패·중단된 답변과 현재 질문은 제외한다. 소유 세션/pending 요청이 없으면
    404/409를 반환하며 DB 오류는 전달한다. 파일·모델 호출은 없다.
    """
    with _connection() as db:
        pending = db.execute("SELECT * FROM messages WHERE id = ? AND role = 'assistant' AND status = 'pending'",
                             (message_id,)).fetchone()
        if pending is None:
            raise HTTPException(409, "진행 중인 대화 요청이 없습니다.")
        conversation = _conversation(db, pending["conversation_id"])
        rows = db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? AND id > ? AND id < ? ORDER BY id",
            (conversation["id"], conversation["last_summarized_message_id"] or 0, message_id),
        ).fetchall()
    turns = []
    question = None
    for row in rows:
        if row["role"] == "user":
            question = dict(row)
        else:
            if question is not None and row["status"] == "completed":
                turns.append([question, dict(row)])
            question = None
    return conversation, turns


def save_memory_summary(conversation_id: str, summary: str, boundary: int) -> None:
    """동일 세션의 완료 답변 경계와 요약을 하나의 트랜잭션으로 저장한다.

    원문을 삭제하지 않는다. 잘못된 경계는 ValueError, DB 오류는 호출자에 전달한다.
    호출자는 해당 세션의 pending 요청을 유지하여 동시 갱신을 차단해야 한다.
    """
    with _connection() as db:
        _conversation(db, conversation_id)
        if not db.execute(
            "SELECT 1 FROM messages WHERE id = ? AND conversation_id = ? AND role = 'assistant' AND status = 'completed'",
            (boundary, conversation_id),
        ).fetchone():
            raise ValueError("요약 경계는 해당 세션의 완료된 답변이어야 합니다.")
        db.execute("UPDATE conversations SET summary = ?, last_summarized_message_id = ? WHERE id = ?",
                   (summary, boundary, conversation_id))
