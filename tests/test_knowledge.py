# RAG 知识库测试：切块/提取/上传后台处理/检索召回/隔离
import json

import pytest

from app.models import KnowledgeChunk, KnowledgeDoc, User
from app.tools.knowledge import chunk_text, extract_text
from app.tools.registry import execute


def _register_login(client, username, password="secret123") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _no_cloud_embedding(monkeypatch):
    """测试隔离：embedding 不碰网络，默认返回固定向量（召回测试可自行覆盖）。"""

    async def _fixed(text, cfg):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr("app.agent.embed.embed_text", _fixed)


# ---------- 纯函数：切块 / 提取 ----------
def test_chunk_text_aggregates_and_caps():
    text = "\n\n".join([f"第{i}段。" + "内容" * 50 for i in range(40)])
    chunks = chunk_text(text)
    assert 0 < len(chunks) <= 300
    assert all(len(c) <= 600 for c in chunks)
    assert all(c.strip() for c in chunks)


def test_chunk_text_hard_splits_long_paragraph_with_overlap():
    para = "甲" * 1500
    chunks = chunk_text(para)
    assert len(chunks) >= 3
    # 相邻块有重叠：第二块的开头出现在第一块尾部
    assert chunks[1][:80] in chunks[0]
    assert all(len(c) <= 600 for c in chunks)


def test_extract_text_txt_gbk_fallback():
    assert extract_text("a.txt", "中文内容".encode("gbk")) == "中文内容"
    assert extract_text("b.md", "# 标题\n正文".encode("utf-8")) == "# 标题\n正文"


def test_extract_text_unsupported_ext_raises():
    with pytest.raises(ValueError, match="仅支持"):
        extract_text("c.docx", b"whatever")


# ---------- 上传 → 后台处理（TestClient 同步执行 BackgroundTasks） ----------
def test_upload_txt_becomes_ready_with_chunks(client, db_session):
    headers = _register_login(client, "kb_user")
    content = "\n\n".join([f"段落{i}：" + "知识" * 80 for i in range(5)]).encode("utf-8")
    resp = client.post(
        "/api/knowledge", files={"file": ("notes.txt", content, "text/plain")}, headers=headers
    )
    assert resp.status_code == 200
    # 后台任务异步切块 embedding：与前端一致，轮询等待 ready
    import time

    body = resp.json()
    deadline = time.time() + 5
    while body["status"] == "pending" and time.time() < deadline:
        time.sleep(0.05)
        body = client.get("/api/knowledge", headers=headers).json()[0]
    assert body["status"] == "ready"
    assert body["chunk_count"] > 0

    db = db_session()
    user = db.query(User).filter(User.username == "kb_user").first()
    doc = db.query(KnowledgeDoc).filter(KnowledgeDoc.user_id == user.id).first()
    assert doc is not None and doc.status == "ready"
    assert db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc.id).count() == doc.chunk_count
    db.close()


def test_upload_unsupported_ext_400(client):
    headers = _register_login(client, "kb_ext")
    resp = client.post(
        "/api/knowledge", files={"file": ("a.docx", b"x", "application/octet-stream")}, headers=headers
    )
    assert resp.status_code == 400


def test_upload_corrupt_pdf_marks_failed(client, db_session):
    headers = _register_login(client, "kb_badpdf")
    resp = client.post(
        "/api/knowledge", files={"file": ("broken.pdf", b"%PDF-not-really", "application/pdf")}, headers=headers
    )
    assert resp.status_code == 200
    listing = client.get("/api/knowledge", headers=headers).json()
    assert listing[0]["status"] == "failed"
    assert listing[0]["error"]


# ---------- 检索工具 ----------
def _seed_ready_doc(db, user_id, filename="资料.txt", vec=(0.1, 0.2, 0.3)):
    doc = KnowledgeDoc(user_id=user_id, filename=filename, status="ready", chunk_count=1)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    db.add(
        KnowledgeChunk(
            user_id=user_id,
            doc_id=doc.id,
            idx=0,
            content="项目代号是「萤火」，负责人是王工。",
            embedding=json.dumps(list(vec)),
        )
    )
    db.commit()


def test_search_knowledge_recalls_top_match(db_session):
    db = db_session()
    user = User(username="kb_search", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    _seed_ready_doc(db, user.id)
    result = execute("search_knowledge", {"query": "项目代号是什么"}, user, db)
    assert result["success"] is True
    assert len(result["results"]) >= 1
    assert result["results"][0]["file"] == "资料.txt"
    assert "萤火" in result["results"][0]["snippet"]
    db.close()


def test_search_knowledge_user_isolation(db_session):
    db = db_session()
    owner = User(username="kb_owner", password_hash="x")
    db.add(owner)
    db.commit()
    db.refresh(owner)
    _seed_ready_doc(db, owner.id)

    intruder = User(username="kb_intruder", password_hash="x")
    db.add(intruder)
    db.commit()
    db.refresh(intruder)
    result = execute("search_knowledge", {"query": "萤火"}, intruder, db)
    assert result["success"] is True
    assert result["results"] == []
    db.close()


def test_search_knowledge_empty_query_fails(db_session):
    db = db_session()
    user = User(username="kb_empty", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    result = execute("search_knowledge", {"query": "  "}, user, db)
    assert result["success"] is False
    db.close()


# ---------- 删除 ----------
def test_delete_document_removes_chunks(client, db_session):
    headers = _register_login(client, "kb_del")
    resp = client.post(
        "/api/knowledge", files={"file": ("del.txt", "要删的文档".encode("utf-8"), "text/plain")}, headers=headers
    )
    doc_id = resp.json()["id"]

    db = db_session()
    assert db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc_id).count() > 0
    db.close()

    resp = client.delete(f"/api/knowledge/{doc_id}", headers=headers)
    assert resp.status_code == 204
    db = db_session()
    assert db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc_id).count() == 0
    assert db.query(KnowledgeDoc).filter(KnowledgeDoc.id == doc_id).count() == 0
    db.close()
