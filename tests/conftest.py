# OneFlow 测试夹具 — 临时 SQLite + dependency_overrides
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app


@pytest.fixture(autouse=True)
def _isolate_settings():
    """每用例快照并还原 settings，杜绝测试间全局状态污染（保证顺序无关）。

    背景：曾有测试文件在模块级改 settings.llm_api_key（收集阶段即生效），
    污染整场运行——表现为单跑通过、全套失败。有此保险丝后，任何用例内对
    settings 的临时修改（含绕过 monkeypatch 的直接赋值）都会在用例后还原。
    """
    snapshot = {name: getattr(settings, name) for name in type(settings).model_fields}
    yield
    for name, value in snapshot.items():
        setattr(settings, name, value)


@pytest.fixture()
def db_session():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        os.unlink(tmp.name)


@pytest.fixture()
def client(db_session):
    def override_get_db():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
