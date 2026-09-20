import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config
from src.classify import get_classifier
from src.logging_store import DecisionLog
from src.pipeline import SupportPipeline
from src.retrieve import Retriever


@pytest.fixture(scope="session")
def retriever():
    return Retriever(persist=False)


@pytest.fixture(scope="session")
def classifier():
    return get_classifier()


@pytest.fixture
def make_pipe(retriever, classifier, tmp_path):
    def _mk(llm):
        return SupportPipeline(classifier=classifier, retriever=retriever, llm=llm,
                               decision_log=DecisionLog(tmp_path / "d.db"))
    return _mk


@pytest.fixture(scope="session")
def val():
    return json.loads((config.DATA_DIR / "validation_tickets.json").read_text())
