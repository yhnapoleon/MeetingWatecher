from typing import Literal
from pydantic import BaseModel, Field


class ArchiveInput(BaseModel):
    meeting: int = Field(ge=0, le=1)
    cursor_ms: int = Field(ge=0)


class SessionInput(BaseModel):
    project_id: str
    meeting: int = Field(ge=0, le=1)
    cursor_ms: int = Field(ge=0)
    archives: list[ArchiveInput] = Field(default_factory=list, max_length=2)


class RunOptions(BaseModel):
    session_id: str
    kind: Literal['qa', 'catchup', 'summary', 'brief', 'comparison', 'validation', 'revise', 'impact', 'handover', 'work'] = 'qa'
    window_ms: int = Field(default=120000, ge=10000, le=300000)
    artifact_id: str | None = None
    template: Literal['design', 'sync'] = 'design'
    research: bool = False
    extract_work: bool = False
    incremental: bool = False


class Section(BaseModel):
    title: str
    text: str
    kind: Literal['fact', 'suggestion', 'unknown'] = 'fact'
    evidence_ids: list[str] = Field(default_factory=list)


class SummaryChange(Section):
    id: str | None = None
    category: Literal['discussion', 'decision', 'proposal', 'question'] = 'discussion'
    prior_topic_id: str | None = None
    relation: Literal['new', 'reaffirmed', 'changed', 'questioned'] = 'new'
    evidence_ids: list[str] = Field(min_length=1)


class TableRow(BaseModel):
    cells: list[str]
    evidence_ids: list[str] = Field(default_factory=list)


class Impact(BaseModel):
    change: str
    target: str
    reason: str
    action: str
    evidence_ids: list[str]


class WorkChange(BaseModel):
    target_guid: str | None = None
    existing_proposal_id: str | None = None
    owner: str
    title: str = Field(min_length=1, max_length=180)
    object_text: str | None = None
    deadline_text: str | None = None
    due_text: str | None = None
    state: Literal['open', 'progress', 'done'] = 'open'
    detail: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(min_length=1)


class WorkConfirmation(BaseModel):
    note: str = Field(default='', max_length=1000)
    due_text: str | None = Field(default=None, max_length=200)
    state: Literal['open', 'progress', 'done'] | None = None


class Answer(BaseModel):
    title: str
    summary: str
    sections: list[Section] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[TableRow] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    impact: Impact | None = None
    work_changes: list[WorkChange] = Field(default_factory=list, max_length=8)
    summary_changes: list[SummaryChange] = Field(default_factory=list, max_length=3)

    def check_evidence(self, evidence):
        allowed = {e['id'] for e in evidence}
        cited = set()
        for s in self.sections:
            if s.kind == 'fact' and not s.evidence_ids:
                raise ValueError('模型返回无引用的事实段，请重试或缩小问题')
            cited.update(s.evidence_ids)
        for r in self.rows:
            if len(r.cells) != len(self.columns):
                raise ValueError('比较表列数不一致')
            cited.update(r.evidence_ids)
        if self.impact:
            cited.update(self.impact.evidence_ids)
            if not self.impact.evidence_ids:
                raise ValueError('影响建议缺少依据')
        for change in self.work_changes:
            cited.update(change.evidence_ids)
        for change in self.summary_changes:
            cited.update(change.evidence_ids)
        if cited - allowed:
            raise ValueError('模型引用了本次证据集之外的原话')
        return self.model_dump()
