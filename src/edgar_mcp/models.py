from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class Company(BaseModel):
    cik: int
    ticker: str
    name: str
    sic: str
    sic_description: str


class Filing(BaseModel):
    accession: str
    form: str
    filed: date
    period: date
    ticker: str
    name: str


class Document(BaseModel):
    filename: str
    type: str
    description: str


class FilingDetail(BaseModel):
    accession: str
    form: str
    cik: int
    ticker: str
    name: str
    filed: date
    period: date
    documents: list[Document]


class Section(BaseModel):
    title: str
    markdown: str
    word_count: int
    source_url: str
    next_cursor: str | None


class Observation(BaseModel):
    period: str
    end_date: date
    value: float
    form: str


class FinancialSeries(BaseModel):
    concept: str
    unit: str
    observations: list[Observation]


class Concept(BaseModel):
    name: str
    label: str
    units: list[str]


class ConceptIndex(BaseModel):
    ticker: str
    taxonomies: dict[str, list[Concept]]


class Insider(BaseModel):
    name: str
    role: str
    net_shares: int
    net_value: float


class InsiderSummary(BaseModel):
    window_start: date
    window_end: date
    insiders: list[Insider]
    total_insider_buying: float
    total_insider_selling: float


class Transaction(BaseModel):
    insider: str
    role: str
    date: date
    type: str
    shares: int
    price: float
    value: float


class InsiderTransactionPage(BaseModel):
    transactions: list[Transaction]
    next_cursor: str | None


class FilingRef(BaseModel):
    accession: str
    form: str
    period: str


class Paragraph(BaseModel):
    text: str


class Modification(BaseModel):
    before: str
    after: str
    similarity: float


class SectionDiff(BaseModel):
    current: FilingRef
    previous: FilingRef
    added: list[Paragraph]
    removed: list[Paragraph]
    modified: list[Modification]
